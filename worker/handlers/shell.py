import asyncio
import os


async def handle(payload: dict) -> dict:
    command = payload["command"]
    env = {**os.environ, **payload.get("env", {})}
    timeout = payload.get("timeout", 3600)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError(f"Command timed out after {timeout}s")

    if proc.returncode != 0:
        raise RuntimeError(
            f"Command exited with code {proc.returncode}:\n{stderr.decode()[:2000]}"
        )

    return {
        "returncode": proc.returncode,
        "stdout": stdout.decode()[:10_000],
        "stderr": stderr.decode()[:2_000],
    }
