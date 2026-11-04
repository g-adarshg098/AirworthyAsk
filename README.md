## Project Name

> AirworthyAsk

Helps aircraft maintenance engineers find the latest DGCA Civil Aviation Requirement (CAR) and revision efficiently.

## Problem

Aircraft Maintenance Engineer (AME) trainees and technicians often study from outdated physical copies or old PDFs of regulations. DGCA Civil Aviation Requirements (CARs) are revised frequently, making it difficult to verify if a specific section is up to date during daily maintenance checks or exam preparation. Manually searching through multiple PDF documents and amendment lists is slow and error-prone. This product instantly indexes and retrieves the most recent DGCA CAR sections and their latest revisions, ensuring compliance and confidence.

---

## Who it is for

- Aircraft Maintenance Engineer (AME) trainees working at MRO hangars near airports (e.g., Chennai Airport).
- Certifying engineers and aviation regulatory exam aspirants needing fast, accurate access to current CAR revisions.

---

## Signature feature

Real-Time Section & Revision Lookup: Instantly search across all DGCA CAR sections to retrieve exact, up-to-date regulatory text along with explicit revision numbers and effective dates.

---

## Hardest problem (my interview story)

Parsing and tracking frequent, non-standardized revision updates published across various DGCA notification PDFs. Ensuring the search system prioritized the latest amendment over older versions required building an accurate metadata extraction pipeline to correctly identify section numbers, revision histories, and effective dates.

---

## Dataset

| Source | Link | Documents | Pages | Licence / terms |
| :--- | :--- | :--- | :--- | :--- |
| DGCA Official Website | [dgca.gov.in](https://dgca.gov.in) | Civil Aviation Requirements (CARs) | Variable | Public Domain / Open Government Data |

---

## 10 real questions

See [docs/QUESTIONS.md](docs/QUESTIONS.md)

---

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
cp .env.example .env                                 # Windows: Copy-Item .env.example .env
uvicorn app.main:app --reload
curl localhost:8000/health
```

### Chat and usage

Set `GEMINI_API_KEY` in `.env`, then start the API and Postgres/pgvector with
`docker compose up --build`. The API creates its usage table on startup.
The first time you set up the database, enable pgvector with:

```powershell
docker compose exec db psql -U app -d rag -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

`POST /chat` accepts `{"message":"..."}` and returns a structured `{"answer":"...","model":"..."}`.
Set `"stream": true` for server-sent events containing JSON `delta` objects and a final `done`
event. Transient provider failures are retried and then sent to the configured fallback model.
`GEMINI_TIMEOUT_SECONDS`, `GEMINI_RETRIES`, `GEMINI_MODEL`, and
`GEMINI_FALLBACK_MODEL` can be set in `.env`.

`GET /usage` reports token totals, estimated cost, and the 100 most recent successful calls.
To estimate cost, set the primary model rates in `GEMINI_INPUT_COST_PER_MILLION` and
`GEMINI_OUTPUT_COST_PER_MILLION` and the fallback model rates in
`GEMINI_FALLBACK_INPUT_COST_PER_MILLION` and
`GEMINI_FALLBACK_OUTPUT_COST_PER_MILLION` (USD per 1 million tokens). Without configured
rates, token usage is still recorded and estimated cost is `null`.

```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d "{\"message\":\"What is a CAR?\"}"
curl http://localhost:8000/usage
```

### Download DGCA PDFs

The scraper follows same-origin HTML pages under the DGCA portal, collects PDF links
(including links stored in `data-url` attributes), checks `robots.txt`, and saves PDFs
to `data/raw/dgca_pdfs` by default. It waits between requests and avoids replacing
existing files. DGCA document links under `/jsp/dgca/` are downloaded from the public
document-storage host used by the portal.

```bash
python tools/scrape_dgca_pdfs.py
```

Options such as the starting page, output directory, crawl limit, and request delay can
be changed with `--url`, `--output`, `--max-pages`, and `--delay`. For example:

```bash
python tools/scrape_dgca_pdfs.py --max-pages 50 --delay 2
```

---

## Live link

[![CI](https://github.com/g-adarshg098/AirworthyAsk/actions/workflows/ci.yml/badge.svg)](https://github.com/g-adarshg098/AirworthyAsk/actions/workflows/ci.yml)

**Live:** https://airworthyask.onrender.com/health · first request after 15 idle minutes takes about a minute (free tier)
