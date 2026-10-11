<div align="center">

<img src="samples/seal.png" width="120" alt="Guilloche seal generated from a certificate serial">

# Bulk Certificate Generator

**One request. Thousands of recipients. One PDF certificate each.**

A FastAPI backend that validates every recipient, renders certificates in the
background, and reports exactly which ones succeeded and which failed.

![Python](https://img.shields.io/badge/python-3.12-1C2541?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-3A7D7B?style=flat-square&logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-1C2541?style=flat-square)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL%20%7C%20SQLite-supported-3A7D7B?style=flat-square&logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-94%20passing-C4492D?style=flat-square)
![Ruff](https://img.shields.io/badge/lint-ruff-1C2541?style=flat-square)

[Quick start](#quick-start) ·
[API walkthrough](#api-walkthrough) ·
[How it works](#how-it-works) ·
[Design decisions](DESIGN.md) ·
[Interview notes](INTERVIEW_NOTES.md)

<br>

<img src="samples/short_name.png" width="820" alt="Sample certificate for Ada Lovelace">

<sub>A4 landscape · vector only · <a href="samples/short_name.pdf">open the PDF</a></sub>

</div>

---

## Highlights

<table>
<tr>
<td width="33%" valign="top">

**Bulk in, per-recipient out**

One `POST` carries up to 5,000 recipients and returns `202 Accepted` in under 100 ms.
Every recipient gets its own tracked row with its own status, serial and download link.

</td>
<td width="33%" valign="top">

**One bad row never sinks the batch**

Invalid names or emails are stored as `rejected` with a machine-readable reason, and
the rest are still issued. Want all-or-nothing? Add `?strict=true`.

</td>
<td width="33%" valign="top">

**Failure isolation and retries**

Each certificate renders and commits on its own. Transient errors retry with
exponential backoff; deterministic errors fail just that row.

</td>
</tr>
<tr>
<td valign="top">

**Survives restarts**

The database is the source of truth, not an in-memory queue. On startup,
interrupted work is reset and resumed automatically.

</td>
<td valign="top">

**Idempotent submissions**

Send an `Idempotency-Key` and a retried request returns the original job instead of
creating a duplicate.

</td>
<td valign="top">

**A certificate worth framing**

An "engraved security print" design with a guilloche seal unique to every serial,
microtext borders and a QR code that links to a verification page.

</td>
</tr>
</table>

## Every certificate is unique

<div align="center">
<img src="samples/seals.png" width="760" alt="Three different seals generated from three serial numbers">

<sub><code>BCG-2026-K7Q4-00001</code> · <code>BCG-2026-K7Q4-00002</code> · <code>BCG-2026-K7Q4-00003</code></sub>
</div>

The rosette seal is drawn procedurally from hypotrochoid and epitrochoid curves. Its
parameters (lobe counts, copies, depth, rotation) come from a SHA-256 hash of the
serial number, each clamped to a range that always looks good. The same serial always
produces the same seal, and a different serial produces a visibly different one, like a
printed fingerprint.

<details>
<summary><b>More samples: long name and accented name</b></summary>
<br>

| Very long name: shrinks, then wraps to two balanced lines | Accented name: full glyph coverage |
|:---:|:---:|
| <img src="samples/long_name.png" width="400"> | <img src="samples/accented_name.png" width="400"> |
| [long_name.pdf](samples/long_name.pdf) | [accented_name.pdf](samples/accented_name.pdf) |

</details>

---

## Quick start

> Needs Python 3.11 or newer. SQLite is the default, so there is nothing else to install.

```bash
make install
```

```bash
make run
```

Open **http://localhost:8000/docs** for interactive API docs. Migrations run
automatically at startup; data lives in `./certgen.db` and PDFs in `./storage/`.

<details>
<summary><b>Without make</b></summary>
<br>

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

```bash
.venv/bin/uvicorn certgen.main:create_app --factory --reload
```

</details>

<details>
<summary><b>With PostgreSQL (docker compose)</b></summary>
<br>

Start Postgres 16 and the API together:

```bash
docker compose up --build
```

Or start only the database, and run the API locally against it:

```bash
docker compose up -d db
```

```bash
DATABASE_URL=postgresql+psycopg://certgen:certgen@localhost:5432/certgen make run
```

</details>

### Make targets

| Command | What it does |
|---|---|
| `make install` | Create `.venv` and install the app with dev tools |
| `make run` | Start the API with auto-reload on port 8000 |
| `make test` | Run the 94 tests (about 4 s) |
| `make lint` / `make fmt` | Ruff checks / auto-format |
| `make migrate` | Apply Alembic migrations to `DATABASE_URL` |
| `make samples` | Re-render `samples/` (PDFs, previews, seals) |

---

## API walkthrough

All endpoints live under `/api/v1`. The examples use
[`examples/sample_request.json`](examples/sample_request.json): 7 recipients, of which 4
are valid and 3 are deliberately broken (blank name, invalid email, duplicate email).

| Method | Path | Purpose |
|:---:|---|---|
| `POST` | `/jobs` | Submit a bulk job (`Idempotency-Key` header, `?strict=true` optional) |
| `GET` | `/jobs/{job_id}` | Status, progress counts and timestamps |
| `GET` | `/jobs/{job_id}/certificates` | Per-recipient results (`?status=`, `?limit=`, `?cursor=`) |
| `GET` | `/jobs/{job_id}/archive.zip` | Streamed ZIP of every issued PDF plus `manifest.csv` |
| `POST` | `/jobs/{job_id}/retry` | Re-queue `failed` rows of a finished job |
| `GET` | `/certificates/{certificate_id}` | One certificate's metadata |
| `GET` | `/certificates/{certificate_id}/pdf` | Download one PDF |
| `GET` | `/verify/{verification_code}` | Public verification (the QR code points here) |
| `GET` | `/healthz` | Liveness and database check (served at the root, not under `/api/v1`) |

### 1. Submit a job

```bash
curl -s -i -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-001" \
  --data @examples/sample_request.json
```

<details>
<summary><b>Response: <code>202 Accepted</code></b></summary>
<br>

```http
HTTP/1.1 202 Accepted
location: /api/v1/jobs/ab1cf731-0292-46c5-bb1e-12a4e0a75491
```

```json
{
  "job_id": "ab1cf731-0292-46c5-bb1e-12a4e0a75491",
  "status": "queued",
  "status_url": "/api/v1/jobs/ab1cf731-0292-46c5-bb1e-12a4e0a75491",
  "accepted_count": 4,
  "rejected_count": 3,
  "rejected": [
    {"position": 4, "recipient_name": "", "recipient_email": "nobody@example.com",
     "error_code": "NAME_BLANK", "error_message": "Recipient name is empty."},
    {"position": 5, "recipient_name": "Grace Hopper", "recipient_email": "not-an-email",
     "error_code": "EMAIL_INVALID", "error_message": "An email address must have an @-sign."},
    {"position": 6, "recipient_name": "Ada Again", "recipient_email": "ADA@example.com",
     "error_code": "EMAIL_DUPLICATE", "error_message": "Email already used by position 0 in this job."}
  ]
}
```

</details>

> **Idempotency:** repeating the request with the same key returns the original job
> (`200` plus `Idempotent-Replayed: true`). The same key with a different body returns
> `409`.

### 2. Poll status and progress

```bash
curl -s http://localhost:8000/api/v1/jobs/$JOB
```

<details>
<summary><b>Response</b></summary>
<br>

```json
{
  "job_id": "ab1cf731-...",
  "status": "completed_with_errors",
  "progress": {"total": 7, "pending": 0, "rendering": 0, "issued": 4,
               "failed": 0, "rejected": 3, "percent_complete": 100.0},
  "created_at": "2026-10-11T09:56:43.993450Z",
  "started_at": "2026-10-11T09:56:43.997034Z",
  "finished_at": "2026-10-11T09:56:44.613061Z",
  "links": {"certificates": "/api/v1/jobs/ab1cf731-.../certificates",
            "archive": "/api/v1/jobs/ab1cf731-.../archive.zip"}
}
```

</details>

### 3. See exactly what happened to each recipient

```bash
curl -s "http://localhost:8000/api/v1/jobs/$JOB/certificates"
```

| position | status | serial / error | recipient |
|:---:|:---:|---|---|
| 0 | issued | `BCG-2026-FJKS-00001` | Ada Lovelace |
| 1 | issued | `BCG-2026-FJKS-00002` | José Müller |
| 2 | issued | `BCG-2026-FJKS-00003` | Zoë Ångström-Núñez Łukasiewicz |
| 3 | issued | `BCG-2026-FJKS-00004` | Maximilian … von Hohenzollern-Sigmaringen-Wittelsbach |
| 4 | rejected | `NAME_BLANK` | *(empty)* |
| 5 | rejected | `EMAIL_INVALID` | Grace Hopper |
| 6 | rejected | `EMAIL_DUPLICATE` | Ada Again |

Each item also carries a `download_url`. Results are paginated: follow `next_cursor`
until it is `null`, and filter with `?status=rejected`.

### 4. Download certificates

One PDF (the filename is built safely from the recipient name, accents included):

```bash
curl -s -OJ http://localhost:8000/api/v1/certificates/<certificate_id>/pdf
```

Everything as a streamed ZIP. It includes `manifest.csv`, which lists **every** row,
including failed and rejected ones:

```bash
curl -s -o certificates.zip http://localhost:8000/api/v1/jobs/$JOB/archive.zip
```

### Errors look the same everywhere

Every error, including FastAPI's own 404 and 422, uses one envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request failed validation.",
    "details": [{"location": "body.recipients", "message": "List should have at least 1 item after validation, not 0"}]
  }
}
```

---

## How it works

```mermaid
flowchart LR
    C([Client]) -->|POST /jobs| A[Validate request<br/>and every recipient]
    A -->|one transaction| DB[(Database<br/>1 job + N rows)]
    A -->|202 Accepted| C
    A -.->|job id| D[Dispatcher<br/>thread pool]
    D --> W[Worker]
    W -->|claim pending row| DB
    W --> R[Render PDF<br/>ReportLab]
    R --> S[(Storage<br/>storage/job/serial.pdf)]
    W -->|issued / failed| DB
    C -->|GET /jobs/id| DB
```

1. **Accept.** The request is validated, and the job plus one row per recipient
   (valid and rejected) are written in a single transaction.
2. **Dispatch.** Only the job id goes to the thread pool. All state stays in the
   database, so a restart loses nothing.
3. **Issue.** A worker claims each pending row atomically, renders it, saves it and
   records the outcome, each certificate in its own transaction.
4. **Report.** Status and progress are counted live from the rows with one `GROUP BY`.

### Status lifecycle

```mermaid
stateDiagram-v2
    direction LR
    [*] --> queued
    queued --> running
    running --> completed: all issued
    running --> completed_with_errors: some issued
    running --> failed: none issued
```

| Certificate status | Meaning |
|---|---|
| `rejected` | Failed validation; never rendered. The reason is in `error_code`. |
| `pending` | Accepted, waiting for a worker |
| `rendering` | A worker is producing it right now |
| `issued` | PDF ready to download |
| `failed` | Rendering failed (after retries, for transient errors). Retryable via `POST /retry`. |

---

## Design decisions

The full reasoning is in **[DESIGN.md](DESIGN.md)**.

| Decision | Why |
|---|---|
| **Background processing**, `202` and polling | A 5,000-row synchronous request could take minutes; `POST` stays under 100 ms |
| **Thread pool, no Celery or Redis** | No extra infrastructure; durability comes from the DB, not the broker |
| **One row per recipient**, created up front | The database alone explains every outcome; the ZIP manifest is one query |
| **Progress counted from the rows** | Stored counters drift under concurrency; a `GROUP BY` can't |
| **Recipient fields typed as plain strings** | `EmailStr` would 422 a whole batch over one typo |
| **Compare-and-set claim** | `UPDATE ... WHERE status='pending'` means no certificate is ever rendered twice |
| **Injected renderer and storage** | Tests swap in a renderer that fails for one named recipient, with no test hooks in production code |

### Performance (measured)

| | |
|---|---|
| `POST /jobs` with 200 recipients | **< 100 ms** |
| Render one certificate | **~63 ms**, ~188 KB PDF |
| 200 certificates end to end, one worker thread | **~17 s** |

---

## Project layout

```
certgen/
├── api/          thin routers · error envelope · presenters · safe download filenames
├── services/     creation · validation · issuing · job runner · queries · ZIP · recovery
├── domain/       status machines · serial numbers · domain exceptions
├── models/       CertificateJob · Certificate (SQLAlchemy 2.0, typed)
├── dispatch/     Dispatcher protocol · ThreadPoolDispatcher · InlineDispatcher
├── rendering/    ReportLab renderer · design tokens · rosette · text fitting · fonts
├── storage/      Storage protocol · LocalDiskStorage
└── migrations/   Alembic
tests/            94 tests: validation, generation, failures, retries, retrieval, recovery
```

## Testing

```bash
make test
```

Each test gets a fresh temporary SQLite database, built through the real Alembic
migration. Jobs run on the `InlineDispatcher`, so they are finished when `POST`
returns, and every assertion is deterministic. Generation tests read the real PDFs back
with `pypdf`; failure tests inject a renderer that fails for one recipient and storage
that fails N times.

## Configuration

All settings are environment variables (or a `.env` file); see
[`.env.example`](.env.example).

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certgen.db` | Any SQLAlchemy URL; Postgres via `postgresql+psycopg://` |
| `DISPATCHER` | `thread` | `thread` for background, `inline` for synchronous |
| `WORKER_POOL_SIZE` | `4` | Jobs processed concurrently |
| `MAX_RECIPIENTS_PER_JOB` | `5000` | Request-level limit (422 above it) |
| `MAX_RENDER_ATTEMPTS` | `3` | Attempts for transient errors |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Printed into each QR code |

## Fonts and licences

Bundled static TTFs, all under the SIL Open Font License (the licences are in
`certgen/rendering/assets/fonts/licenses/`):
**Cormorant Garamond** (name, achievement line) · **IBM Plex Sans Condensed** (labels) ·
**IBM Plex Mono** (serial, date, microtext) · **Noto Serif** (fallback for missing glyphs).

<div align="center">
<br>
<sub>Built with FastAPI, SQLAlchemy and ReportLab · <a href="DESIGN.md">Design</a> · <a href="INTERVIEW_NOTES.md">Interview notes</a></sub>
</div>
