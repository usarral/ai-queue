#!/usr/bin/env python3
"""
WoL service — checks every CHECK_INTERVAL seconds if there are pending tasks.
If there are and the AI server is not responding to ping, sends a magic packet.
"""

import asyncio
import logging
import os
import socket
import struct

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]
AI_SERVER_IP = os.environ.get("AI_SERVER_IP", "")
AI_SERVER_MAC = os.environ.get("AI_SERVER_MAC", "")
BROADCAST_IP = os.environ.get("BROADCAST_IP", "255.255.255.255")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "120"))


def send_magic_packet(mac: str, broadcast: str):
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast, 9))
    log.info("Magic packet sent to %s (broadcast %s)", mac, broadcast)


async def ping(ip: str, timeout: float = 2.0) -> bool:
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


async def count_pending(conn: asyncpg.Connection) -> int:
    return await conn.fetchval("SELECT count(*) FROM tasks WHERE status = 'pending'")


async def main():
    if not AI_SERVER_MAC:
        log.warning("AI_SERVER_MAC not set — WoL disabled, only monitoring")
    if not AI_SERVER_IP:
        log.warning("AI_SERVER_IP not set — cannot check if server is online")

    pg_url = DATABASE_URL.replace("postgresql://", "postgres://")
    conn = await asyncpg.connect(pg_url)
    log.info("WoL service started (interval=%ds, target=%s mac=%s)", CHECK_INTERVAL, AI_SERVER_IP, AI_SERVER_MAC)

    try:
        while True:
            try:
                pending = await count_pending(conn)
                log.info("Pending tasks: %d", pending)

                if pending > 0 and AI_SERVER_MAC:
                    server_online = await ping(AI_SERVER_IP) if AI_SERVER_IP else False
                    if not server_online:
                        log.info("AI server offline — sending WoL packet")
                        send_magic_packet(AI_SERVER_MAC, BROADCAST_IP)
                    else:
                        log.info("AI server online — no WoL needed")
            except Exception as exc:
                log.error("Check failed: %s", exc)

            await asyncio.sleep(CHECK_INTERVAL)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
