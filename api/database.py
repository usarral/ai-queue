import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


SCHEMA_STATEMENTS = [
    'CREATE EXTENSION IF NOT EXISTS "pgcrypto"',
    """DO $$ BEGIN
        CREATE TYPE task_status AS ENUM ('pending','processing','completed','failed','cancelled');
    EXCEPTION WHEN duplicate_object THEN NULL;
    END $$""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        started_at      TIMESTAMPTZ,
        completed_at    TIMESTAMPTZ,
        type            VARCHAR(64) NOT NULL,
        priority        SMALLINT NOT NULL DEFAULT 5,
        input_payload   JSONB NOT NULL,
        output_payload  JSONB,
        status          task_status NOT NULL DEFAULT 'pending',
        error_message   TEXT,
        retry_count     SMALLINT NOT NULL DEFAULT 0,
        max_retries     SMALLINT NOT NULL DEFAULT 3,
        worker_id       VARCHAR(128),
        stream_id       VARCHAR(64),
        tags            TEXT[] DEFAULT '{}'
    )""",
    """CREATE TABLE IF NOT EXISTS task_events (
        id          BIGSERIAL PRIMARY KEY,
        task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        event_type  VARCHAR(32) NOT NULL,
        details     JSONB
    )""",
    """CREATE TABLE IF NOT EXISTS workers (
        id              VARCHAR(128) PRIMARY KEY,
        last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        registered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        status          VARCHAR(16) NOT NULL DEFAULT 'active',
        hostname        VARCHAR(255),
        capabilities    TEXT[]
    )""",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_pending ON tasks(priority ASC, created_at ASC) WHERE status = 'pending'",
    "CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id)",
]


async def init_db():
    from sqlalchemy import text
    async with engine.begin() as conn:
        for stmt in SCHEMA_STATEMENTS:
            await conn.execute(text(stmt))
