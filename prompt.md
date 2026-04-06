# Wine Voice Assistant — Claude Code Prompt

Build a voice-enabled web app that lets users ask questions about a wine dataset and receive answers in text and spoken voice.

## Architecture

**Backend:** FastAPI (Python) — holds the SQLite database, handles wine queries, proxies all API calls (Claude for answers, OpenAI for voice). Keeps all API keys server-side.

**Frontend:** React (via Vite) — single-page app, no routing needed. Communicates with FastAPI backend via REST.

- **Database:** SQLite (server-side, via Python's built-in `sqlite3`)
- **Voice Input:** OpenAI Whisper API (audio recorded in browser, sent to backend, backend calls Whisper)
- **Query Brain:** Anthropic Claude API (`claude-sonnet-4-20250514`), called from FastAPI backend
- **Voice Output:** OpenAI TTS API (backend generates audio, streams MP3 to frontend for playback)

## Project Structure

```
wine-voice-assistant/
├── backend/
│   ├── main.py            # FastAPI app, endpoints
│   ├── db.py              # SQLite setup, CSV import, query helpers
│   ├── llm.py             # Claude API integration
│   ├── voice.py           # OpenAI Whisper (STT) + TTS integration
│   └── requirements.txt   # fastapi, uvicorn, anthropic, openai, python-multipart, pandas
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js             # Audio recording, API calls, playback, UI state
└── data/
    └── wines.csv           # Downloaded from Google Sheets
```

## Data

Download this Google Sheet as CSV on startup or keep a local copy:
https://docs.google.com/spreadsheets/d/1Bkv3Jb_8YuLUG2rWUhJhQBdaGjQCMFfwF9oJ5jrYDSA/export?format=csv

On server startup, parse the CSV and create a SQLite table. Use `DROP TABLE IF EXISTS wines` before `CREATE TABLE` to ensure a clean import on every restart (idempotent startup):

```sql
CREATE TABLE wines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  producer TEXT,
  country TEXT,
  region TEXT,
  appellation TEXT,
  varietal TEXT,
  vintage TEXT,
  color TEXT,
  abv REAL,
  price REAL NOT NULL,
  ratings TEXT,       -- raw JSON array, stored as string
  top_score INTEGER,  -- highest score extracted from ratings JSON during import, for sorting
  image_url TEXT,
  reference_url TEXT
);
```

The `id` comes from the CSV `Id` column — it's the wine.com product ID and is unique per row. This matters because the dataset has duplicate wine names in different bottle sizes (e.g., Veuve Clicquot Brut at 375ml, 750ml, 1500ml).

The `ratings` column contains JSON like: `[{"source": "James Suckling", "score": 93, "max_score": 100, "note": "..."}]`. Do NOT parse or flatten it. Store the raw JSON string. The LLM will interpret it.

Only `name` and `price` are NOT NULL. Everything else is nullable — the dataset has legitimate gaps (missing ABV, blank vintage for NV wines, empty appellations, etc.).

`top_score` is derived during CSV import: parse the ratings JSON in Python, extract the highest `score` value across all sources, and store it as a plain integer. For example, `[{"score": 93}, {"score": 91}]` → `top_score = 93`. Wines with no ratings get `top_score = NULL`.

Skip these CSV columns during import: `Upc`, `volume_ml`. Map `Id` to `id`, `Retail` to `price`.

## Backend — FastAPI Endpoints

### `POST /api/transcribe`

Accepts audio from the browser (WebM/WAV blob), sends it to OpenAI Whisper API, returns the transcript.

Request: `multipart/form-data` with an `audio` file field.

**Internal flow:**
1. Receive the audio file from the frontend
2. Send to OpenAI Whisper API (`whisper-1` model) for transcription
3. Return the transcript text

Response:
```json
{
  "transcript": "What are your best wines under fifty dollars?"
}
```

### `POST /api/ask`

The main endpoint. Accepts the user's transcribed question, queries the DB, sends context to Claude, returns the answer as both text AND audio.

Request body:
```json
{
  "question": "What are your best rated wines under $50?"
}
```

**Internal flow:**
1. Parse the question for obvious filters using simple regex and keyword matching:
   - **Price:** Look for patterns like "under $50", "below 30 dollars", "less than $100", "between $20 and $50", "cheapest", "most expensive". Map them to SQL price conditions (e.g., `WHERE price <= 50`, `ORDER BY price DESC LIMIT 1`).
   - **Color:** Check if the question contains "red", "white", "rosé", "sparkling", "dessert". Exact word match → `WHERE color = 'red'`.
   - **Country/Region:** Match against a known list pulled from distinct values in the DB on startup (e.g., "Italy", "France", "Burgundy", "Napa Valley", "Rioja", "Argentina"). Match → `WHERE country LIKE '%Italy%' OR region LIKE '%Italy%'`.
   - **Varietal:** Same approach — match against known values from the DB (e.g., "Malbec", "Chardonnay", "Pinot Noir", "Cabernet Sauvignon"). Match → `WHERE varietal LIKE '%Malbec%'`.
   - This is best-effort, not the brain of the app. Claude is the brain. The pre-filter just reduces noise.
2. Query SQLite with those filters to get a relevant subset (max 50 wines)
3. If no filters detected or parser catches nothing, query only wines that have ratings, sorted by highest score: `SELECT * FROM wines WHERE top_score IS NOT NULL ORDER BY top_score DESC LIMIT 100`. This gives Claude a representative, high-quality subset for generic/subjective questions like "good housewarming gift".
4. Call Claude API with the filtered wines + user question
5. Send Claude's answer text to OpenAI TTS API (`tts-1` model, `nova` voice) to generate audio
6. Return both the text answer and the audio (base64-encoded MP3, or as a separate audio endpoint)

Response:
```json
{
  "answer": "Here are some top-rated wines under $50...",
  "audio_base64": "<base64-encoded MP3>",
  "wines_considered": 42
}
```

Alternative: instead of base64 in JSON, create a `GET /api/audio/{id}` endpoint that streams the MP3 file. The frontend then sets an `<audio>` element's `src` to this URL. This avoids large JSON payloads.

**Claude API prompt structure:**

```
System: You are a friendly, knowledgeable wine sommelier. You answer questions
based ONLY on the wine catalog provided. Keep answers conversational and concise
(3-4 sentences max, unless the user asks for a list). If listing wines, limit to
5 unless asked for more. Always mention the wine name, price, and rating when
recommending. If the question cannot be answered from the catalog, say so politely.
If the question is ambiguous, make a reasonable interpretation and state your
assumption. Never invent or fabricate any data — not wines, prices, ratings, regions, or any other details. Every fact in your answer must come directly from the provided catalog.

User: Wine catalog (JSON):
${json.dumps(filtered_wines)}

User question: "${question}"
```

Use model `claude-sonnet-4-20250514`. Set max_tokens to 500.

### `GET /` — Serve the frontend

Use FastAPI's `StaticFiles` to serve the frontend directory, or mount `index.html` at the root.

## Frontend — Audio Recording

Since we're using Whisper instead of the Web Speech API, the frontend needs to record audio from the microphone and send it to the backend.

**Recording flow:**
1. User clicks mic button → request microphone access via `navigator.mediaDevices.getUserMedia()`
2. Create a `MediaRecorder` to capture audio (use `audio/webm` format)
3. User clicks mic button again (or auto-stop after silence) → stop recording
4. Get the audio blob from MediaRecorder
5. Send the blob to `POST /api/transcribe` as `multipart/form-data`
6. Display the returned transcript on screen
7. Send the transcript to `POST /api/ask`
8. Display the text answer
9. Play the returned audio (decode base64 to blob, create object URL, play via `<audio>` element or `new Audio()`)

**Important:** `python-multipart` must be in requirements.txt for FastAPI to handle file uploads.

## Frontend — UI Design

Minimal, clean, single page:

- **Center of page:** Large microphone button (toggles recording on/off)
- **Above mic:** The transcribed question (what the user said)
- **Below mic:** The text answer from the assistant
- **Status indicator:** Visual states for: idle, recording (pulsing red animation), transcribing (loading), thinking (loading), speaking (speaker animation)
- **Color scheme:** Dark, elegant, wine-themed (deep burgundy, cream text, subtle gold accents)
- **No wine list table, no sidebar, no navigation.** The voice interaction is the entire interface.

## Ambiguity Handling

The LLM handles most ambiguity naturally via the system prompt. Additionally:

- **Out of scope** ("What's the weather?"): The system prompt instructs Claude to only answer from catalog data, so it will decline gracefully.
- **No results** from SQL pre-filter: Fall back to sending a broad sample of wines and let the LLM figure it out.
- **Subjective questions** ("good housewarming gift"): The LLM interprets these. The system prompt encourages reasonable assumptions.
- **Transcription errors**: Display the transcript so the user can see what Whisper heard. Add a "try again" option.

## Example Questions to Test

- "Which are the best-rated wines under $50?"
- "What do you have from Burgundy?"
- "What's the most expensive bottle you have?"
- "Which bottles would make a good housewarming gift?"
- "Any good Italian reds?"
- "What sparkling wines do you have under $30?"
- "Tell me about the Tignanello"
- "What's the weather?" (should gracefully decline)

## API Keys & Environment

Both API keys are read from environment variables. Never expose them to the frontend.

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## Technical Notes

- OpenAI Whisper API accepts audio files up to 25MB. Short voice questions will be well under this.
- OpenAI TTS `tts-1` is the faster/cheaper model (good for real-time). `tts-1-hd` is higher quality but slower. Start with `tts-1`.
- For TTS voice, use `nova` — it sounds warm and friendly, good fit for a sommelier persona.
- Handle the CSV ratings column carefully — it contains JSON with commas and quotes that can confuse CSV parsers. Use Python's `pandas.read_csv()` which handles this well.
- CORS: Add `CORSMiddleware` to FastAPI to allow frontend requests during development. Alternatively, configure Vite's dev server proxy in `vite.config.js` to forward `/api` requests to FastAPI (e.g., `proxy: { '/api': 'http://localhost:8000' }`).
- `python-multipart` is required for file upload handling in FastAPI.
- Run backend with: `uvicorn backend.main:app --reload`
- Run frontend with: `cd frontend && npm run dev`
- This works in ALL browsers (not just Chrome) since voice input is handled server-side by Whisper, not by the Web Speech API.
- **Optional enhancement:** Add backend-side caching — store the last question + answer with a short TTL (e.g., 30 seconds). If the exact same question comes in again, return the cached result instead of calling Claude and TTS again. Saves API costs and improves response time for repeated questions.