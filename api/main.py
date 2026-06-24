import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Security, HTTPException
from fastapi.security.api_key import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

from database import init_db, get_db, SessionLocal
from task_queue import ensure_group, pending_entries
from routers import tasks, workers, system

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

API_KEY = os.environ.get("API_KEY", "")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_key(key: str | None = Security(api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(401, "Invalid or missing API key")


async def _recovery_loop():
    """Restarts stale 'processing' tasks every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        try:
            async with SessionLocal() as db:
                from sqlalchemy import text
                result = await db.execute(text("""
                    UPDATE tasks
                    SET status = CASE
                            WHEN retry_count >= max_retries THEN 'failed'::task_status
                            ELSE 'pending'::task_status
                        END,
                        retry_count = retry_count + 1,
                        updated_at = now()
                    WHERE status = 'processing'
                      AND updated_at < now() - interval '10 minutes'
                    RETURNING id, status
                """))
                rows = result.mappings().all()
                if rows:
                    log.info("Recovery: restarted %d stale tasks", len(rows))
                await db.commit()

            await pending_entries(min_idle_ms=600_000)
        except Exception as exc:
            log.warning("Recovery loop error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_group()
    asyncio.create_task(_recovery_loop())
    log.info("AI Queue API ready")
    yield


app = FastAPI(title="AI Queue API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix="/api", dependencies=[Security(verify_key)])
app.include_router(workers.router, prefix="/api", dependencies=[Security(verify_key)])
app.include_router(system.router, prefix="/api", dependencies=[Security(verify_key)])


@app.get("/api/stats")
async def stats_shortcut():
    from routers.system import stats
    from database import get_db
    async with SessionLocal() as db:
        return await stats(db)


@app.get("/healthz")
async def health():
    return {"ok": True}
