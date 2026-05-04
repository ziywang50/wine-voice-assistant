# Wine Voice Assistant

A voice-powered wine sommelier. Speak a question about the wine catalog and get a spoken answer back, powered by OpenAI Whisper (transcription), Claude (reasoning), and OpenAI TTS (speech).

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- An `ANTHROPIC_API_KEY` and an `OPENAI_API_KEY`

---

## Setup & Running

### 1. Environment variables

Create `wine-voice-assistant/.env`:

```
ANTHROPIC_API_KEY=your-anthropic-key
OPENAI_API_KEY=your-openai-key
```

### 2. Backend

```bash
cd wine-voice-assistant
pip install -r backend/requirements.txt
cd backend
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`. On first start it downloads the wine catalog CSV and initialises the SQLite database at `data/wines.db`.

### 3. Frontend (development)

```bash
cd wine-voice-assistant/frontend
npm install
npm run dev
```

Vite starts at `http://localhost:5173` and proxies all `/api/*` requests to the backend.

### 4. Frontend (production build)

```bash
cd wine-voice-assistant/frontend
npm run build
```

The compiled output goes to `frontend/dist/`. FastAPI serves it automatically from the root path, so the backend alone is sufficient in production.

---

## Frontend Overview

**Stack:** React 19 + Vite, plain CSS (no component library).

```
src/
  main.jsx               # Entry point — mounts the app
  App.jsx                # Root component — wires hook to UI
  hooks/
    useVoice.js          # All state, audio capture, and API calls
  components/
    MicButton.jsx        # Mic / stop / spinner / cancel button
    StatusLabel.jsx      # Text label reflecting current status
    TranscriptArea.jsx   # Displays the user's spoken question
    AnswerArea.jsx       # Displays Claude's answer or error
  App.css                # All styles
```

### State machine (`useVoice.js`)

The hook drives the UI through six states:

| State | Meaning |
|---|---|
| `idle` | Waiting for user input |
| `recording` | Mic is active, capturing audio |
| `transcribing` | Audio sent to `/api/transcribe`, awaiting result |
| `thinking` | Transcript sent to `/api/ask`, Claude is working |
| `speaking` | TTS audio is playing |
| `error` | Something went wrong |

Key behaviours:
- Audio is recorded via `MediaRecorder` and sent as a multipart blob.
- Both fetch calls (`/api/transcribe` and `/api/ask`) use an `AbortController` so they can be cancelled mid-flight.
- The TTS response arrives as a base64-encoded MP3, decoded into a Blob URL and played with the Web Audio API.
- Cancelling during any busy state aborts the request (or stops playback) and returns to `idle`.

---

## Backend Overview

**Stack:** FastAPI + Uvicorn, SQLite (via the standard library), Pandas for CSV import.

```
backend/
  main.py   # FastAPI app, API routes, pre-filter logic
  db.py     # CSV download, SQLite init, query helpers
  llm.py    # Claude API integration
  voice.py  # OpenAI Whisper (STT) and TTS
data/
  wines.csv # Downloaded from Google Sheets on first run
  wines.db  # SQLite database, created from the CSV
```

### API routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/transcribe` | Accepts a multipart audio file, returns `{ transcript }` via Whisper |
| `POST` | `/api/ask` | Accepts `{ question }`, returns `{ answer, audio_base64, wines_considered }` |

### Request pipeline (`/api/ask`)

1. **Parse** — regex extracts price ranges, wine color, geographic terms, and varietals from the question.
2. **Query** — filtered wines are fetched from SQLite, ordered by `top_score`. Falls back to top-rated wines if no filters match.
3. **Reason** — the filtered catalog is sent to Claude as JSON context with the user's question. Claude is prompted to answer only from the provided data.
4. **Speak** — the answer text is converted to MP3 via OpenAI TTS and returned as base64. TTS failure is non-fatal; the text answer is still returned.
5. **Cache** — responses are cached in memory for 30 seconds to avoid redundant API calls for repeated questions.

### Database

The wine catalog is sourced from a Google Sheet, imported into SQLite at startup. Each wine row includes name, producer, country, region, appellation, varietal, vintage, color, ABV, price, and `professional_ratings` (a JSON array of critic scores). A `top_score` column is derived from the max score in that array and used for sorting.
