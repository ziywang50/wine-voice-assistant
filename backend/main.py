import base64
import time
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from pathlib import Path

import db, llm, voice

load_dotenv()

# ---------------------------------------------------------------------------
# Simple in-process cache (question → answer+audio, TTL 30 s)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 30


def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Wine Voice Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    try:
        transcript = voice.transcribe_audio(audio_bytes, filename=audio.filename or "audio.webm")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}")
    return {"transcript": transcript}


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
async def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    cached = _cache_get(question)
    if cached:
        return cached

    try:
        answer, wines = llm.ask_claude(question)
    except Exception as exc:
        print(f"[ERROR] Claude API: {exc}")
        raise HTTPException(status_code=500, detail=f"Claude API error: {exc}")

    try:
        audio_bytes = voice.text_to_speech(answer)
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as exc:
        audio_base64 = None
        print(f"[warn] TTS failed: {exc}")

    result = {
        "answer": answer,
        "audio_base64": audio_base64,
        "wines": wines,
    }
    _cache_set(question, result)
    return result


# ---------------------------------------------------------------------------
# Serve frontend (must be last so API routes take priority)
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
