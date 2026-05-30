# Erasmus Assistant

Read-only student assistant for the data produced by `erasmus_discovery`.

This app does not crawl, scrape, normalize, extract, update, or modify discovery data. It only reads:

- `../erasmus_discovery/data/erasmus.db`
- `../erasmus_discovery/chroma_db`

## Architecture

1. Student asks a question in the frontend.
2. Backend detects the question intent.
3. Backend retrieves structured facts from SQLite.
4. Backend retrieves general knowledge chunks from Chroma.
5. Backend builds a small evidence package.
6. Gemini answers only from that evidence.
7. Frontend shows the answer, sources, and matching agreement rows.

## Install

```powershell
cd erasmus_assistant
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Create `.env`:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and set `GEMINI_API_KEY`.

If `.env` is not created, the backend will try to read Gemini settings from `../erasmus_discovery/.env`.

## Run

```powershell
cd erasmus_assistant
.\.venv\Scripts\uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Or use the wrapper:

```powershell
cd erasmus_assistant
.\.venv\Scripts\python.exe scripts\run_server.py
```

Open:

```text
http://127.0.0.1:8000
```

## Endpoints

- `GET /health`
- `GET /api/stats`
- `GET /api/universities`
- `POST /api/ask`

Example request:

```json
{
  "question": "Which universities in Italy can I go to from University of Thessaly?"
}
```

## Guardrails

- SQLite is opened with `mode=ro`.
- The assistant does not import discovery pipeline scripts.
- The assistant does not write to SQLite or Chroma.
- If evidence is missing, the answer should say that the stored data does not contain enough information.
- Source URLs are returned with every answer.
