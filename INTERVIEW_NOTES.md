# Interview Notes

A walkthrough for explaining and changing the code live.

## Mental model in one paragraph

`POST /jobs` validates every recipient and writes **one job row plus one row per
recipient** in a single transaction, then hands the job id to a dispatcher and returns
`202`. A worker thread repeatedly asks the database "which rows of this job are still
pending?", and for each one claims it, renders a PDF, saves it and records the outcome
in its own transaction. Everything the API reports (status, progress, results, ZIP)
is read back from those rows. The database is the single source of truth; the thread
pool is only a trigger.

## Layering rule

```
api/routes  ->  services  ->  domain + models        (rendering/ and storage/ are leaf
   (HTTP)       (logic)       (rules, tables)          modules with no DB access)
```

Routers never import `select`. Services never build URLs or HTTP responses.
`composition.py` is the only module that decides which implementations are used.

## Request lifecycle, file by file

### 1. Startup: `certgen/main.py`
- `create_app()` builds FastAPI, registers the error handlers and routers.
- In the `lifespan`:
  1. `db/migrations.py:upgrade_to_head` runs Alembic, if enabled.
  2. `composition.py:build_app_services` builds the engine, session factory, storage,
     renderer, and the dispatcher with `run_job` bound to them.
  3. `dispatcher.start()` starts the thread pool.
  4. `services/startup_recovery.py:recover_interrupted_work` resets `rendering ->
     pending`, and every unfinished job is re-submitted.

### 2. Submit: `POST /api/v1/jobs`
1. **`api/routes/jobs.py:submit_job`**. FastAPI parses the body into
   `schemas/job_requests.py:CreateJobRequest`. Request-level problems (no title, empty
   list) raise `RequestValidationError`, which `api/error_handlers.py` turns into the
   422 envelope.
2. **`services/job_creation.py:create_job`**:
   - checks `MAX_RECIPIENTS_PER_JOB` (`TooManyRecipients` -> 422);
   - fingerprints the body; if an `Idempotency-Key` matches an existing job, it replays
     it, or raises 409 if the body differs;
   - `services/recipient_validation.py:screen_recipients` splits rows into valid
     (normalised) and rejected (with a code);
   - strict mode with any rejected row raises `InvalidRecipients` -> 422;
   - `_build_job` creates the job, `pending` rows with serial and verification code, and
     `rejected` rows with their error. One `commit()`. On an `IntegrityError` it retries
     with a new serial prefix, or replays a concurrent same-key job.
3. **Back in the router**: `present_job_created`, the `Location` header, then
   `dispatcher.submit(job_id)`, called only after the commit, so the worker can see the
   rows.

### 3. Process: worker thread
1. **`dispatch/dispatchers.py:ThreadPoolDispatcher.submit`** puts
   `run_job(job_id)` on the executor (`InlineDispatcher` runs it immediately).
2. **`services/job_runner.py:run_job`**:
   - `_mark_running` moves `queued -> running` via `domain/statuses.py:transition_job`;
   - `_pending_chunks` yields the ids of `pending` rows, `PROCESSING_CHUNK_SIZE` at a
     time, re-querying each chunk;
   - `issue_certificate` runs for each id;
   - `_finalise` loads `job_progress.py:load_job_progress` (GROUP BY), and
     `final_job_status` sets the terminal status and `finished_at`.
3. **`services/certificate_issuing.py:issue_certificate`**:
   - `_claim`: a conditional `UPDATE ... WHERE status='pending'` (compare-and-set), then
     builds a `RenderContext` from job plus row;
   - `_render_and_store` (no DB session): `renderer.render()` then `storage.save()`.
     `OSError` is retried with backoff; anything else becomes `RENDER_ERROR`;
   - `_record_outcome`: `transition_certificate` to `issued` or `failed`, plus file key
     or error, and attempts. Commit.
4. **`rendering/security_print.py:SecurityPrintRenderer.render`** draws the page.
   Helpers: `design_tokens.py` (all measurements), `rosette.py` (serial -> seal),
   `text_fitting.py` (name shrink/wrap), `fonts.py` (registration and fallback).
5. **`storage/local_disk.py:LocalDiskStorage.save`** writes atomically to
   `storage/{job_id}/{serial}.pdf`.

### 4. Read results
- `GET /jobs/{id}`: `routes/jobs.py:read_job_status`, which calls
  `certificate_queries.get_job` and `job_progress.load_job_progress`, then
  `presenters.present_job_status`.
- `GET /jobs/{id}/certificates`: `certificate_queries.list_job_certificates`
  (keyset cursor on `position`).
- `GET /certificates/{id}/pdf`: `certificate_queries.load_issued_pdf` (404 if not
  issued), with `api/content_disposition.py:attachment_header` for the filename.
- `GET /jobs/{id}/archive.zip`: `archive_export.snapshot_job_archive` (DB) and then
  `stream_job_archive` (no DB) inside a `StreamingResponse`.
- `GET /verify/{code}`: `certificate_queries.find_issued_by_verification_code`.

## Where to look for X

| Question | File |
|---|---|
| Which status moves are legal? | `domain/statuses.py` |
| How is a serial built? | `domain/serials.py` |
| Which HTTP status does an error get? | `api/error_handlers.py:DOMAIN_ERROR_STATUS` |
| Recipient rules and their order | `services/recipient_validation.py` |
| Retry and backoff policy | `services/certificate_issuing.py:_render_and_store` |
| What's transient vs deterministic? | `certificate_issuing.py:TRANSIENT_ERRORS` |
| Colours, sizes, positions | `rendering/design_tokens.py` |
| Which implementations are used | `composition.py` |
| All settings | `config.py`, `.env.example` |

## Likely change requests

### "Add a second template"
1. Create `rendering/<new_template>.py` with a class implementing
   `render(context) -> bytes` (it can reuse `rosette.py`, `text_fitting.py`, `fonts.py`).
2. Add `template: TemplateName = "security_print"` to `CertificateDetails`
   (`schemas/job_requests.py`) and a `template` column on `CertificateJob`, with a new
   Alembic revision (`alembic revision --autogenerate -m "add template"`; review it).
3. In `composition.py`, build a `dict[TemplateName, CertificateRenderer]` and inject a
   small `RendererRegistry` into `IssuingDependencies` instead of a single renderer.
4. In `certificate_issuing.py:_claim`, carry `job.template` into the render step and
   pick the renderer from the registry.
5. Tests: render each template; a job with `template="new"` produces a PDF containing
   the new template's text.

### "Email the certificates to recipients"
- Keep it out of the render transaction: a failed email must not mark a valid
  certificate `failed`.
- Add a `CertificateMailer` protocol (`send(recipient, pdf_bytes)`) with an SMTP/SES
  implementation and a fake for tests, injected through `composition.py`.
- Track delivery separately: new columns `email_status` (`not_sent / sent / bounced /
  failed`), `email_attempts` and `emailed_at`, or a `certificate_deliveries` table if
  re-sends need history.
- Trigger: after `_record_outcome` marks a row `issued`, the runner sends the email in
  its own step with the same transient-retry pattern. Or, more decoupled, a second
  dispatcher job, "deliver job X", that walks `issued AND email_status='not_sent'`.
- Opt-in per job with `send_email: bool`; never send from the request thread.

### "Cancel a job"
1. `domain/statuses.py`: add `JobStatus.CANCELLED` (transitions
   `queued|running -> cancelled`) and `CertificateStatus.CANCELLED`
   (`pending -> cancelled`). Add both to the migration's CHECK constraints (new
   revision).
2. `services/job_cancellation.py`: in one transaction, transition the job and run a
   bulk `UPDATE certificates SET status='cancelled' WHERE job_id=:id AND
   status='pending'`.
3. `routes/jobs.py`: `POST /jobs/{id}/cancel` returns 202, or 409 if already final.
4. The runner needs almost no change: `_pending_chunks` finds no pending rows, so it
   stops. Rows already `rendering` finish normally. `_finalise` must skip a job that's
   no longer `running` (it already does).
5. `JobProgress` gains a `cancelled` count; `final_job_status` is unaffected because the
   cancel path sets the status itself.

### "Add a field to the certificate" (for example a course duration)
1. `schemas/job_requests.py:CertificateDetails`: add `duration_hours: int | None = None`.
2. `models/job.py`: add the column, then run
   `alembic revision --autogenerate -m "add duration"` and review the generated file.
3. `job_creation.py:_build_job`: copy the field. `presenters.py` and
   `job_responses.py:CertificateDetailsView`: expose it.
4. `rendering/protocol.py:RenderContext`: add it. `certificate_issuing.py:_render_context`:
   pass it.
5. `security_print.py:_layout_text_block`: append a `_TextRun`. Add any new size to
   `design_tokens.py`. Then `make samples` and look at the PNGs.
6. Per-recipient fields (for example a grade) go on `RecipientInput` and `Certificate`
   instead, with a rule in `recipient_validation.py` if they need validating.

### "Switch to Celery"
1. Add `certgen/dispatch/celery_app.py` with a task
   `run_job_task(job_id: str)` that builds the same `IssuingDependencies` (factor
   `composition.py` so workers can reuse it) and calls `run_job`.
2. Add `CeleryDispatcher.submit(job_id)`, which calls `run_job_task.delay(str(job_id))`.
   `start` and `shutdown` are no-ops.
3. Add `DispatcherKind.CELERY` and choose it in `composition.py`.
4. Nothing else changes. Routers, services and tests stay as they are, because
   messages carry only an id and the database stays the source of truth. Celery's
   `acks_late=True` plus the compare-and-set claim make redelivery safe.
5. Startup recovery moves to a periodic task (Celery beat) with lease expiry instead of
   API startup.

### "We need 100k recipients in one job"
- Raise `MAX_RECIPIENTS_PER_JOB`, and accept the list as a CSV upload
  (`UploadFile`) streamed through the validator, rather than one 20 MB JSON body.
- `_build_job`: insert rows in batches (`session.execute(insert(Certificate), rows)` in
  chunks of 5,000) instead of ORM objects. Consider building the job in a background
  step and returning 202 even earlier.
- Rendering: about 63 ms each is roughly 105 CPU-minutes. Move to multi-process
  workers with `SELECT ... FOR UPDATE SKIP LOCKED` (DESIGN.md section 13) so it scales
  with cores and machines.
- Storage: S3 plus presigned URLs. The archive becomes a background job writing the
  ZIP to object storage, polled like any other job.
- Five-digit serials end at 99,999. Widen `format_serial` to six digits (and
  `String(32)` still fits).

## Questions an interviewer is likely to ask

- **Why not validate emails with Pydantic `EmailStr`?** It would 422 the whole batch
  for one typo. See DESIGN.md section 5.
- **Why compute progress with GROUP BY?** Counters drift under concurrency; the rows
  can't lie. One indexed query.
- **What if the server crashes mid-job?** The rows say exactly where it stopped.
  Startup recovery resets `rendering -> pending` and re-dispatches. Storage writes are
  atomic and idempotent per serial.
- **Can a certificate be rendered twice?** No. The claim is a conditional UPDATE, and
  only one worker gets `rowcount = 1`.
- **Why threads if the GIL serialises rendering?** They give concurrency across jobs,
  I/O overlap, and a responsive API. For real parallelism, swap the dispatcher; the
  design already has the seam.
- **How do tests force exactly one certificate to fail?** They inject
  `FailingForRecipientRenderer("Alan Turing")` through `build_app_services`. There's no
  test code in production modules.
- **Is the PDF deterministic?** The design is: same serial, same seal, same layout.
  The bytes differ by ReportLab's creation timestamp and document ID, which is fine
  for a certificate.
