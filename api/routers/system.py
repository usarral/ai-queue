import asyncio
import os
import socket
import struct

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

router = APIRouter(prefix="/system", tags=["system"])

AI_SERVER_IP = os.environ.get("AI_SERVER_IP", "")
AI_SERVER_MAC = os.environ.get("AI_SERVER_MAC", "")
BROADCAST_IP = os.environ.get("BROADCAST_IP", "255.255.255.255")


def _send_magic_packet(mac: str, broadcast: str):
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast, 9))


async def _ping(ip: str, timeout: float = 2.0) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(int(timeout)), ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=timeout + 1)
        return proc.returncode == 0
    except Exception:
        return False


@router.get("/ai-status")
async def ai_status():
    if not AI_SERVER_IP:
        return {"online": None, "reason": "AI_SERVER_IP not configured"}
    online = await _ping(AI_SERVER_IP)
    return {"online": online, "ip": AI_SERVER_IP}


@router.post("/wakeup")
async def manual_wakeup():
    if not AI_SERVER_MAC:
        return {"sent": False, "reason": "AI_SERVER_MAC not configured"}
    _send_magic_packet(AI_SERVER_MAC, BROADCAST_IP)
    return {"sent": True, "mac": AI_SERVER_MAC}


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(text("""
        SELECT status, count(*) AS count FROM tasks GROUP BY status
    """))
    counts = {r["status"]: r["count"] for r in rows.mappings()}
    return {
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
    }
