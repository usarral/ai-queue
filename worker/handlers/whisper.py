import asyncio
import os


async def handle(payload: dict) -> dict:
    file_path = payload["file_path"]
    language = payload.get("language", "auto")
    model = payload.get("model", "base")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Audio file not found: {file_path}")

    # Try faster-whisper first, fall back to openai-whisper CLI
    try:
        from faster_whisper import WhisperModel
        wm = WhisperModel(model, device="auto", compute_type="auto")
        lang_arg = None if language == "auto" else language
        segments, info = wm.transcribe(file_path, language=lang_arg)
        text = " ".join(s.text.strip() for s in segments)
        return {
            "text": text,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "backend": "faster-whisper",
        }
    except ImportError:
        pass

    # Fallback: whisper CLI
    cmd = ["whisper", file_path, "--model", model, "--output_format", "txt"]
    if language != "auto":
        cmd += ["--language", language]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"whisper CLI failed:\n{stderr.decode()[:2000]}")

    txt_path = file_path.rsplit(".", 1)[0] + ".txt"
    text = open(txt_path).read() if os.path.exists(txt_path) else stdout.decode()
    return {"text": text.strip(), "language": language, "backend": "whisper-cli"}
