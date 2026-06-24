import httpx

OLLAMA_URL = "http://localhost:11434"


async def handle(payload: dict) -> dict:
    model = payload.get("model", "llama3.2")
    prompt = payload["prompt"]
    options = payload.get("options", {})

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/generate", json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            **options,
        })
        resp.raise_for_status()
        data = resp.json()

    return {
        "response": data.get("response"),
        "model": data.get("model"),
        "eval_count": data.get("eval_count"),
        "prompt_eval_count": data.get("prompt_eval_count"),
    }
