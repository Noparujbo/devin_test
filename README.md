# devin-test — Shortly

A small URL shortener: submit a long URL, get a short code, and track click counts and
timestamps on a dashboard.

Stack: FastAPI + SQLite, with a single-page vanilla-JS dashboard served from `static/`.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -e . uvicorn
DB_PATH=./urls.db .venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.

## Tests

```bash
.venv/bin/pytest
```

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/shorten` | `{"url": "...", "custom_code": "optional"}` → short link |
| GET | `/api/links` | all links with click counts |
| GET | `/api/links/{code}/clicks` | per-click timestamps, referer, user agent |
| DELETE | `/api/links/{code}` | remove a link |
| GET | `/{code}` | 307 redirect, records a click |

In production `DB_PATH` defaults to `/data/urls.db` on a persistent volume.
