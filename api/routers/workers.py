from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

router = APIRouter(prefix="/workers", tags=["workers"])


class HeartbeatPayload(BaseModel):
    id: str
    hostname: str | None = None
    capabilities: list[str] = []


@router.post("/heartbeat")
async def heartbeat(body: HeartbeatPayload, db: AsyncSession = Depends(get_db)):
    import json
    await db.execute(text("""
        INSERT INTO workers (id, hostname, capabilities, last_seen_at, status)
        VALUES (:id, :hostname, :caps, now(), 'active')
        ON CONFLICT (id) DO UPDATE SET
            last_seen_at = now(),
            hostname = EXCLUDED.hostname,
            capabilities = EXCLUDED.capabilities,
            status = 'active'
    """), {
        "id": body.id,
        "hostname": body.hostname,
        "caps": body.capabilities,
    })
    await db.commit()
    return {"ok": True}


@router.get("")
async def list_workers(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(text("""
        SELECT id, hostname, capabilities, last_seen_at, registered_at, status
        FROM workers ORDER BY last_seen_at DESC
    """))
    now = datetime.now(timezone.utc)
    workers = []
    for w in rows.mappings():
        d = dict(w)
        seconds_ago = (now - d["last_seen_at"].replace(tzinfo=timezone.utc)).total_seconds()
        d["online"] = seconds_ago < 90
        workers.append(d)
    return workers
