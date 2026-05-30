# Erasmus URL Discovery

Python-only project for discovering useful Erasmus source URLs from manually provided university Erasmus base pages.

The project currently covers URL discovery/selection and the first working content ingestion layer:

1. Load manual Erasmus base URLs from `config/universities.json`
2. Discover URLs from sitemaps or limited internal crawling
3. Prefilter discovered URLs with Erasmus keywords
4. Use Gemini to classify candidate URLs
5. Store approved source URLs in `selected_urls`
6. Fetch approved URLs one at a time
7. Extract HTML/PDF/DOCX/XLSX text where supported
8. Use Gemini to clean and translate stored content into English
9. Store cleaned documents, chunks, agreement rows, and ChromaDB vectors

## Storage

SQLite is used for metadata and URL-selection state.

- `universities`: manual university configuration copied from JSON
- `base_urls`: the exact manual Erasmus base URLs used as crawl roots
- `discovered_urls`: URLs found from each base URL
- `url_classifications`: every Gemini decision for a candidate URL
- `selected_urls`: approved URLs that should later be scraped by the next project phase
- `scraped_documents`: cleaned English document text produced from selected URLs
- `chunks`: text chunks derived from cleaned documents
- `erasmus_agreements`: high/medium confidence student Erasmus partner agreements
- `agreement_candidates`: low-confidence agreement-like records for review
- `structured_extraction_logs`: one extraction log per processed document
- `logs`: important pipeline events

Important provenance links:

- `discovered_urls.base_url_id` points to the manual base URL that produced the discovered URL
- `url_classifications.base_url_id` points to the same base URL
- `selected_urls.base_url_id` points to the same base URL
- `scraped_documents.selected_url_id` points to the approved URL that produced the content
- `chunks.selected_url_id` points to the same selected URL
- every selected row keeps the original `url`
- every document/agreement row keeps `source_url`

## Install

From this folder:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

## Configure Gemini

Create or edit `.env` in this folder:

```text
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.1-flash-lite
```

Optional backup keys can be added in priority order. The project uses the first key first, then rotates to the next key if Gemini returns a `429` quota/rate-limit response:

```text
GEMINI_API_KEY=primary_key_here
GEMINI_API_KEY_1=backup_key_1_here
GEMINI_API_KEY_2=backup_key_2_here
GEMINI_API_KEY_3=backup_key_3_here
```

Alternatively:

```text
GEMINI_API_KEYS=primary_key_here,backup_key_1_here,backup_key_2_here,backup_key_3_here
```

The project uses the Gemini REST API directly with `requests`.

## Configure Universities

Edit `config/universities.json`.

Each university is added manually:

```json
[
  {
    "key": "uth",
    "name": "University of Thessaly",
    "country": "Greece",
    "city": "Volos",
    "base_erasmus_url": "https://erasmus.uth.gr/en/",
    "allowed_domains": ["erasmus.uth.gr"],
    "enabled": true
  }
]
```

The crawler starts only from `base_erasmus_url` and stays inside `allowed_domains`.

## Run

Initialize SQLite and load the university config:

```bash
python scripts/init_db.py
```

Discover URLs and run the keyword prefilter:

```bash
python scripts/run_discovery.py
```

Start discovery again from a clean URL-discovery table:

```bash
python scripts/run_discovery.py --reset-existing
```

Resume after an interrupted run by skipping universities that already have discovered URLs:

```bash
python scripts/run_discovery.py --skip-existing
```

Run discovery for one university only:

```bash
python scripts/run_discovery.py --university-key uth --reset-existing
```

Tune the conservative fallback crawler:

```bash
python scripts/run_discovery.py --reset-existing --max-depth 2 --max-pages 100 --delay 0.4
```

Recompute only `candidate` / `ignored` status after changing keywords:

```bash
python scripts/run_discovery.py --prefilter-only
```

Classify already discovered candidate URLs with Gemini:

```bash
python scripts/run_url_selection.py
```

Classify only one university:

```bash
python scripts/run_url_selection.py --university-key uth
```

Limit classification while testing:

```bash
python scripts/run_url_selection.py --university-key uth --limit 20
```

Run discovery and Gemini URL selection together:

```bash
python scripts/run_full_pipeline.py
```

Run a fresh Gemini URL selection, ignoring old saved decisions:

```bash
python scripts/run_full_pipeline.py --reset-existing
```

Clear only downstream content ingestion data while preserving discovery and selected URLs:

```bash
python scripts/clear_content_data.py
```

Run content ingestion from approved selected URLs:

```bash
python scripts/run_content_ingestion.py
```

Test content ingestion on one university with a small limit:

```bash
python scripts/run_content_ingestion.py --university-key uop --limit 2
```

Run content ingestion for one configured base URL:

```bash
python scripts/run_content_ingestion.py --base-url-id 14 --limit 5
```

Reprocess URLs that already have stored documents:

```bash
python scripts/run_content_ingestion.py --include-processed
```

Clear downstream content data and then ingest again:

```bash
python scripts/run_content_ingestion.py --reset-content
```

## Important Rules

- No fake data is inserted.
- The crawler does not scrape whole university domains.
- Crawling starts only from manually configured Erasmus base URLs.
- Crawling stays inside `allowed_domains`.
- URLs already classified are skipped on normal runs.
- Use `--reset-existing` only when you want to classify again from scratch.
- Failed Gemini classifications can be retried.
- PDF, XLS, XLSX, DOC, and DOCX links may be selected as useful source URLs.
- Approved URLs are stored in `selected_urls`; content ingestion starts from that table.
- Content ingestion must store cleaned English text, not raw scraped text.
- Staff/teaching-only agreements must not become student Erasmus agreement rows.
