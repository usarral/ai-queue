#!/usr/bin/env python3
"""
AI Queue Worker — long-polls the API for tasks and executes them locally.
Runs as a systemd service on the AI server.
"""

import asyncio
import json
import logging
import os
import platform
import threading

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_URL = os.environ["API_URL"].rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
WORKER_ID = os.environ.get("WORKER_ID", platform.node())
POLL_BLOCK = int(os.environ.get("POLL_BLOCK", "30"))
HEARTBEAT_INTERVAL = 30

HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

from handlers import ollama, shell, whisper

HANDLERS = {
    "ollama_prompt": ollama.handle,
    "shell_command": shell.handle,
    "whisper_transcription": whisper.handle,
}


async def register():
    async with httpx.AsyncClient(headers=HEADERS, timeout=10) as client:
        await client.post(f"{API_URL}/api/workers/heartbeat", json={
            "id": WORKER_ID,
            "hostname": platform.node(),
            "capabilities": list(HANDLERS.keys()),
        })
    log.info("Registered as worker '%s'", WORKER_ID)


async def heartbeat_loop():
    async with httpx.AsyncClient(headers=HEADERS, timeout=10) as client:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await client.post(f"{API_URL}/api/workers/heartbeat", json={
                    "id": WORKER_ID,
                    "hostname": platform.node(),
                    "capabilities": list(HANDLERS.keys()),
                })
            except Exception as exc:
                log.warning("Heartbeat failed: %s", exc)


async def patch_task(client: httpx.AsyncClient, task_id: str, **kwargs):
    await client.patch(f"{API_URL}/api/tasks/{task_id}", json=kwargs)


async def process_task(task: dict):
    task_id = task["id"]
    task_type = task["type"]
    handler = HANDLERS.get(task_type)

    async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
        await patch_task(client, task_id, status="processing", worker_id=WORKER_ID, stream_id=task["stream_id"])

    if not handler:
        async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
            await patch_task(client, task_id, status="failed", error_message=f"No handler for type '{task_type}'")
        return

    log.info("Processing task %s (type=%s)", task_id, task_type)
    try:
        output = await handler(task["input_payload"])
        async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
            await patch_task(client, task_id, status="completed", output_payload=output)
        log.info("Task %s completed", task_id)
    except Exception as exc:
        log.error("Task %s failed: %s", task_id, exc)
        async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
            await patch_task(client, task_id, status="failed", error_message=str(exc))


async def poll_loop():
    log.info("Polling %s/api/tasks/next (block=%ds)", API_URL, POLL_BLOCK)
    async with httpx.AsyncClient(headers=HEADERS, timeout=POLL_BLOCK + 5) as client:
        while True:
            try:
                resp = await client.get(
                    f"{API_URL}/api/tasks/next",
                    params={"block": POLL_BLOCK},
                    timeout=POLL_BLOCK + 5,
                )
                resp.raise_for_status()
                task = resp.json()
                if task:
                    await process_task(task)
            except httpx.TimeoutException:
                pass
            except Exception as exc:
                log.error("Poll error: %s", exc)
                await asyncio.sleep(10)


async def main():
    await register()
    await asyncio.gather(poll_loop(), heartbeat_loop())


if __name__ == "__main__":
    asyncio.run(main())
