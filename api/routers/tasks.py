from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from task_queue import enqueue, next_task, ack

router = APIRouter(prefix="/tasks", tags=["tasks"])

VALID_TYPES = {"ollama_prompt", "shell_command", "whisper_transcription"}
VALID_STATUSES = {"pending", "processing", "completed", "failed", "cancelled"}


class TaskCreate(BaseModel):
    type: str
    input_payload: dict[str, Any]
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    tags: list[str] = []


class TaskPatch(BaseModel):
    status: str | None = None
    output_payload: dict[str, Any] | None = None
    error_message: str | None = None
    worker_id: str | None = None
    stream_id: str | None = None


@router.post("", status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    if body.type not in VALID_TYPES:
        raise HTTPException(400, f"Unknown task type '{body.type}'. Valid: {sorted(VALID_TYPES)}")

    row = await db.execute(text("""
        INSERT INTO tasks (type, input_payload, priority, max_retries, tags)
        VALUES (:type, cast(:payload as jsonb), :priority, :max_retries, :tags)
        RETURNING id, created_at, status
    """), {
        "type": body.type,
        "payload": json.dumps(body.input_payload),
        "priority": body.priority,
        "max_retries": body.max_retries,
        "tags": body.tags,
    })
    task = row.mappings().one()

    stream_id = await enqueue(str(task["id"]), body.type, body.priority)

    await db.execute(text("UPDATE tasks SET stream_id = :sid WHERE id = :id"),
                     {"sid": stream_id, "id": str(task["id"])})

    await db.execute(text("""
        INSERT INTO task_events (task_id, event_type, details)
        VALUES (:id, 'created', cast(:details as jsonb))
    """), {"id": str(task["id"]), "details": json.dumps({"type": body.type})})

    await db.commit()
    return {"id": str(task["id"]), "status": task["status"], "created_at": task["created_at"]}


@router.get("")
async def list_tasks(
    status: str | None = None,
    type: str | None = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    conditions = ["1=1"]
    params: dict = {"offset": (page - 1) * limit, "limit": limit}
    if status:
        conditions.append("status = cast(:status as task_status)")
        params["status"] = status
    if type:
        conditions.append("type = :type")
        params["type"] = type

    where = " AND ".join(conditions)
    rows = await db.execute(text(f"""
        SELECT id, created_at, updated_at, started_at, completed_at,
               type, priority, status, error_message, retry_count, worker_id, tags
        FROM tasks WHERE {where}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """), params)
    total = await db.execute(text(f"SELECT count(*) FROM tasks WHERE {where}"), params)
    return {
        "items": [dict(r) for r in rows.mappings()],
        "page": page,
        "limit": limit,
        "total": total.scalar(),
    }


@router.get("/next")
async def get_next_task(block: int = Query(default=30, ge=1, le=60), db: AsyncSession = Depends(get_db)):
    entry = await next_task(block_ms=block * 1000)
    if not entry:
        return None

    task_id = entry["task_id"]
    row = await db.execute(text("""
        SELECT id, type, input_payload, priority, max_retries, retry_count
        FROM tasks WHERE id = :id AND status = 'pending'
    """), {"id": task_id})
    task = row.mappings().first()

    if not task:
        await ack(entry["stream_id"])
        return None

    return {
        "id": task_id,
        "type": task["type"],
        "input_payload": task["input_payload"],
        "priority": task["priority"],
        "max_retries": task["max_retries"],
        "retry_count": task["retry_count"],
        "stream_id": entry["stream_id"],
    }


@router.get("/{task_id}")
async def get_task(task_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.execute(text("""
        SELECT id, created_at, updated_at, started_at, completed_at,
               type, priority, input_payload, output_payload, status,
               error_message, retry_count, max_retries, worker_id, tags
        FROM tasks WHERE id = :id
    """), {"id": str(task_id)})
    task = row.mappings().first()
    if not task:
        raise HTTPException(404, "Task not found")

    events = await db.execute(text("""
        SELECT event_type, occurred_at, details FROM task_events
        WHERE task_id = :id ORDER BY occurred_at ASC
    """), {"id": str(task_id)})

    return {**dict(task), "events": [dict(e) for e in events.mappings()]}


@router.patch("/{task_id}")
async def patch_task(task_id: UUID, body: TaskPatch, db: AsyncSession = Depends(get_db)):
    row = await db.execute(text("SELECT status, stream_id FROM tasks WHERE id = :id"), {"id": str(task_id)})
    task = row.mappings().first()
    if not task:
        raise HTTPException(404, "Task not found")

    if body.status and body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status '{body.status}'")

    now = datetime.now(timezone.utc)
    updates = ["updated_at = :now"]
    params: dict = {"id": str(task_id), "now": now}

    if body.status:
        updates.append("status = cast(:status as task_status)")
        params["status"] = body.status
        if body.status == "processing":
            updates.append("started_at = :now")
        elif body.status in ("completed", "failed", "cancelled"):
            updates.append("completed_at = :now")
    if body.output_payload is not None:
        updates.append("output_payload = cast(:output as jsonb)")
        params["output"] = json.dumps(body.output_payload)
    if body.error_message is not None:
        updates.append("error_message = :error_message")
        params["error_message"] = body.error_message
    if body.worker_id is not None:
        updates.append("worker_id = :worker_id")
        params["worker_id"] = body.worker_id
    if body.stream_id is not None:
        updates.append("stream_id = :stream_id")
        params["stream_id"] = body.stream_id

    await db.execute(text(f"UPDATE tasks SET {', '.join(updates)} WHERE id = :id"), params)

    if body.status:
        await db.execute(text("""
            INSERT INTO task_events (task_id, event_type, details)
            VALUES (:id, :event, cast(:details as jsonb))
        """), {
            "id": str(task_id),
            "event": body.status,
            "details": json.dumps({"worker_id": body.worker_id, "error": body.error_message}),
        })

    if body.status in ("completed", "failed", "cancelled") and task["stream_id"]:
        await ack(task["stream_id"])

    await db.commit()
    return {"id": str(task_id), "status": body.status or task["status"]}


@router.delete("/{task_id}", status_code=204)
async def cancel_task(task_id: UUID, db: AsyncSession = Depends(get_db)):
    row = await db.execute(text("SELECT status FROM tasks WHERE id = :id"), {"id": str(task_id)})
    task = row.mappings().first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task["status"] != "pending":
        raise HTTPException(409, f"Cannot cancel task with status '{task['status']}'")

    await db.execute(text("""
        UPDATE tasks SET status = cast('cancelled' as task_status), updated_at = now()
        WHERE id = :id
    """), {"id": str(task_id)})
    await db.commit()
