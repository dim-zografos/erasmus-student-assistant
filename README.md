# UTH Erasmus Assistant

This repository contains a two-part Erasmus information system:

1. `erasmus_discovery` collects, selects, cleans, structures, and stores Erasmus information.
2. `erasmus_assistant` reads the stored data and provides a student-facing assistant UI.

The assistant is read-only. It does not crawl websites, update data, or modify the discovery database.

## Project Structure

```text
UTH_Erasmus_Assistant/
  erasmus_discovery/
    config/universities.json      # manually selected Erasmus base URLs
    data/                         # generated SQLite database, ignored by Git
    chroma_db/                    # generated Chroma vector index, ignored by Git
    scripts/                      # discovery, selection, ingestion scripts
    src/                          # discovery pipeline source code
    .env.example                  # Gemini settings template
    requirements.txt
    README.md

  erasmus_assistant/
    backend/                      # FastAPI read-only assistant backend
    frontend/                     # chat UI
    scripts/run_server.py
    .env.example                  # Gemini/settings template
    requirements.txt
    README.md
```

## Requirements

- Python 3.11 or newer recommended
- Gemini API key
- Internet connection for discovery/classification/normalization/assistant answers

## 1. Clone The Project

```bash
git clone <your-repository-url>
cd UTH_Erasmus_Assistant
```

## 2. Configure Discovery

Create the discovery environment file:

```powershell
cd erasmus_discovery
Copy-Item .env.example .env
```

On macOS/Linux:

```bash
cd erasmus_discovery
cp .env.example .env
```

Edit `erasmus_discovery/.env`:

```text
GEMINI_API_KEY=your_primary_gemini_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
```

Optional backup keys:

```text
GEMINI_API_KEY_1=your_backup_key_1
GEMINI_API_KEY_2=your_backup_key_2
GEMINI_API_KEY_3=your_backup_key_3
```

## 3. Configure Universities

Edit:

```text
erasmus_discovery/config/universities.json
```

Each entry must be manually chosen:

```json
{
  "key": "uth",
  "name": "University of Thessaly",
  "country": "Greece",
  "city": "Volos",
  "base_erasmus_url": "https://erasmus.uth.gr/en/",
  "allowed_domains": ["erasmus.uth.gr"],
  "enabled": true
}
```

Important:

- `base_erasmus_url` is where discovery starts.
- `allowed_domains` prevents crawling unrelated websites.
- The crawler does not scrape a whole university domain unless that domain is explicitly allowed and reachable from the Erasmus base URL.

## 4. Install Discovery Dependencies

Windows PowerShell:

```powershell
cd erasmus_discovery
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

macOS/Linux:

```bash
cd erasmus_discovery
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 5. Run Discovery And Data Ingestion

From `erasmus_discovery`:

```powershell
.\.venv\Scripts\python.exe scripts\init_db.py
.\.venv\Scripts\python.exe scripts\run_discovery.py
.\.venv\Scripts\python.exe scripts\run_url_selection.py
.\.venv\Scripts\python.exe scripts\run_content_ingestion.py
```

Useful one-university commands:

```powershell
.\.venv\Scripts\python.exe scripts\run_discovery.py --university-key uth --reset-existing
.\.venv\Scripts\python.exe scripts\run_url_selection.py --university-key uth
.\.venv\Scripts\python.exe scripts\run_content_ingestion.py --university-key uth
```

Useful testing command:

```powershell
.\.venv\Scripts\python.exe scripts\run_content_ingestion.py --university-key uth --limit 5
```

The generated data will be stored locally in:

```text
erasmus_discovery/data/erasmus.db
erasmus_discovery/chroma_db/
```

These generated files are ignored by Git.

## 6. Configure Assistant

The assistant can either use its own `.env` file or fall back to `erasmus_discovery/.env`.

Create the assistant environment file:

```powershell
cd ..\erasmus_assistant
Copy-Item .env.example .env
```

Edit `erasmus_assistant/.env`:

```text
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
```

Optional path overrides:

```text
ERASMUS_DB_PATH=../erasmus_discovery/data/erasmus.db
ERASMUS_CHROMA_PATH=../erasmus_discovery/chroma_db
```

## 7. Install Assistant Dependencies

Windows PowerShell:

```powershell
cd erasmus_assistant
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

macOS/Linux:

```bash
cd erasmus_assistant
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 8. Run The Assistant UI

From `erasmus_assistant`:

```powershell
.\.venv\Scripts\python.exe scripts\run_server.py
```

Open:

```text
http://127.0.0.1:8000
```

Useful health check:

```text
http://127.0.0.1:8000/health
```

## How The System Works

### Discovery

The project starts from manually configured Erasmus base URLs. It tries sitemap discovery first and uses limited internal crawling if needed. It stays inside `allowed_domains`.

### URL Selection

Discovered URLs are filtered with Erasmus keywords and classified with Gemini. Selected URLs are stored in `selected_urls`.

### Content Ingestion

Selected URLs are processed one at a time:

```text
fetch URL -> extract text -> clean/translate to English -> store document -> extract agreements -> chunk -> update Chroma
```

The pipeline stores cleaned useful content, not raw scraped text.

### Storage

SQLite stores structured data:

- universities
- base URLs
- selected URLs
- cleaned documents
- chunks
- confirmed Erasmus agreements
- agreement candidates
- logs/skips

ChromaDB stores vector-searchable chunks for general Erasmus questions.

### Assistant

The assistant:

1. receives a student question
2. detects intent
3. searches SQLite for structured facts
4. searches Chroma for general knowledge
5. sends only retrieved evidence to Gemini
6. returns an answer with sources

It opens SQLite in read-only mode and does not modify discovery data.
