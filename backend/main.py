import base64
import re
import time
from contextlib import asynccontextmanager
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

from . import db, llm, voice

#load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Simple in-process cache (question → answer+audio, TTL 30 s)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 30  # seconds


def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def _cache_set(key: str, value: dict) -> None:
    _cache[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Pre-filter helpers
# ---------------------------------------------------------------------------

COLOR_KEYWORDS = {
    "red": "red",
    "white": "white",
    "rosé": "rosé",
    "rose": "rosé",
    "sparkling": "sparkling",
    "dessert": "dessert",
    "champagne": "sparkling",
    "prosecco": "sparkling",
    "cava": "sparkling",
}

PRICE_PATTERNS = [
    # "under $50" / "below $50" / "less than $50"
    (r"(?:under|below|less than|cheaper than)\s*\$?\s*(\d+(?:\.\d+)?)", "max"),
    # "over $50" / "above $50" / "more than $50"
    (r"(?:over|above|more than|at least)\s*\$?\s*(\d+(?:\.\d+)?)", "min"),
    # "between $20 and $50" / "between 20 and 50 dollars"
    (r"between\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:and|to|-)\s*\$?\s*(\d+(?:\.\d+)?)", "range"),
    # "$20 to $50"
    (r"\$\s*(\d+(?:\.\d+)?)\s*(?:to|-)\s*\$?\s*(\d+(?:\.\d+)?)", "range"),
]


def _parse_price(question: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """Return (price_min, price_max, order_override).
    order_override is 'asc' for 'cheapest', 'desc' for 'most expensive'."""
    q = question.lower()
    for pattern, kind in PRICE_PATTERNS:
        m = re.search(pattern, q)
        if m:
            if kind == "max":
                return None, float(m.group(1)), None
            if kind == "min":
                return float(m.group(1)), None, None
            if kind == "range":
                lo, hi = float(m.group(1)), float(m.group(2))
                return (min(lo, hi), max(lo, hi), None)

    if "cheapest" in q or "most affordable" in q or "lowest price" in q:
        return None, None, "asc"
    if "most expensive" in q or "priciest" in q or "highest price" in q:
        return None, None, "desc"
    return None, None, None


def _parse_color(question: str) -> Optional[str]:
    q = question.lower()
    for kw, color in COLOR_KEYWORDS.items():
        # word-boundary match to avoid false positives
        if re.search(rf"\b{re.escape(kw)}\b", q):
            return color
    return None


def _parse_geo(question: str, filter_cache: dict) -> Optional[str]:
    q = question.lower()
    all_geo = (
        filter_cache.get("countries", [])
        + filter_cache.get("regions", [])
        + filter_cache.get("appellations", [])
    )
    # Longer names first to prefer specific matches
    for term in sorted(all_geo, key=len, reverse=True):
        if term and re.search(rf"\b{re.escape(term)}\b", q):
            return term
    return None


def _parse_varietal(question: str, filter_cache: dict) -> Optional[str]:
    q = question.lower()
    for varietal in sorted(filter_cache.get("varietals", []), key=len, reverse=True):
        if varietal and re.search(rf"\b{re.escape(varietal)}\b", q):
            return varietal
    return None


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

    filter_cache = db.get_filter_cache()

    price_min, price_max, order_override = _parse_price(question)
    color = _parse_color(question)
    geo_term = _parse_geo(question, filter_cache)
    varietal = _parse_varietal(question, filter_cache)

    any_filter = any([price_min, price_max, order_override, color, geo_term, varietal])

    if any_filter:
        if order_override == "asc":
            order_by = "price ASC"
            limit = 20
        elif order_override == "desc":
            order_by = "price DESC"
            limit = 5
        else:
            order_by = "top_score DESC NULLS LAST"
            limit = 50

        wines = db.query_wines(
            price_min=price_min,
            price_max=price_max,
            color=color,
            geo_term=geo_term,
            varietal=varietal,
            order_by=order_by,
            limit=limit,
        )
        # Fall back to top-rated if filters return nothing
        if not wines:
            wines = db.query_top_rated(100)
    else:
        wines = db.query_top_rated(100)

    try:
        answer = llm.ask_claude(question, wines)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Claude API error: {exc}")

    try:
        audio_bytes = voice.text_to_speech(answer)
        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
    except Exception as exc:
        # TTS failure is non-fatal — return text without audio
        audio_base64 = None
        print(f"[warn] TTS failed: {exc}")

    result = {
        "answer": answer,
        "audio_base64": audio_base64,
        "wines_considered": len(wines),
    }
    _cache_set(question, result)
    return result


# ---------------------------------------------------------------------------
# Serve frontend (must be last so API routes take priority)
# ---------------------------------------------------------------------------

import os
from pathlib import Path

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
