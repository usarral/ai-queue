import os
import asyncio
import redis.asyncio as aioredis

STREAM_KEY = "ai:tasks:stream"
GROUP_NAME = "ai-workers"
CONSUMER_NAME = os.environ.get("WORKER_ID", "api-server")

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    return _redis


async def ensure_group():
    r = get_redis()
    try:
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


async def enqueue(task_id: str, task_type: str, priority: int) -> str:
    r = get_redis()
    stream_id = await r.xadd(STREAM_KEY, {
        "task_id": task_id,
        "type": task_type,
        "priority": str(priority),
    })
    return stream_id


async def next_task(block_ms: int = 30_000) -> dict | None:
    """Long-poll: waits up to block_ms for the next pending task."""
    r = get_redis()
    await ensure_group()
    result = await r.xreadgroup(
        GROUP_NAME, CONSUMER_NAME, {STREAM_KEY: ">"},
        count=1, block=block_ms,
    )
    if not result:
        return None
    _, entries = result[0]
    stream_id, data = entries[0]
    return {"stream_id": stream_id, **data}


async def ack(stream_id: str):
    r = get_redis()
    await r.xack(STREAM_KEY, GROUP_NAME, stream_id)


async def pending_entries(min_idle_ms: int = 600_000) -> list[dict]:
    r = get_redis()
    result = await r.xpending_range(STREAM_KEY, GROUP_NAME, "-", "+", count=100)
    stale = [e for e in result if e["time_since_delivered"] >= min_idle_ms]
    claimed = []
    for e in stale:
        entries = await r.xclaim(STREAM_KEY, GROUP_NAME, "recovery", min_idle_ms, [e["message_id"]])
        for sid, data in entries:
            claimed.append({"stream_id": sid, **data})
    return claimed
