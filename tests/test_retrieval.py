"""Retrieving results: listing, metadata, PDF download, ZIP archive, verification."""

import csv
import io
import zipfile

from fastapi.testclient import TestClient

from tests.conftest import (
    JOBS_URL,
    ClientFactory,
    FailingForRecipientRenderer,
    FakeRenderer,
    job_payload,
    recipients,
)


def submit(client: TestClient, payload: dict[str, object]) -> str:
    response = client.post(JOBS_URL, json=payload)
    assert response.status_code == 202
    job_id: str = response.json()["job_id"]
    return job_id


def certificate_items(client: TestClient, job_id: str, query: str = "") -> list[dict[str, object]]:
    items: list[dict[str, object]] = client.get(f"{JOBS_URL}/{job_id}/certificates{query}").json()[
        "items"
    ]
    return items


# --- listing and metadata --------------------------------------------------------------


def test_listing_shows_every_row_with_download_urls_for_issued_ones(client: TestClient) -> None:
    payload = job_payload([*recipients("Ada Lovelace"), {"name": "", "email": "x@example.com"}])
    job_id = submit(client, payload)

    issued, rejected = certificate_items(client, job_id)

    assert issued["status"] == "issued"
    assert issued["download_url"] == f"/api/v1/certificates/{issued['certificate_id']}/pdf"
    assert rejected["status"] == "rejected"
    assert rejected["download_url"] is None
    assert rejected["serial"] is None


def test_listing_filters_by_status(client: TestClient) -> None:
    payload = job_payload([*recipients("Ada Lovelace"), {"name": "", "email": "x@example.com"}])
    job_id = submit(client, payload)

    rejected = certificate_items(client, job_id, "?status=rejected")

    assert [item["position"] for item in rejected] == [1]


def test_listing_paginates_with_a_cursor(client: TestClient) -> None:
    names = [f"Person {index}" for index in range(5)]
    job_id = submit(client, job_payload(recipients(*names)))

    positions: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        query = f"?limit=2&cursor={cursor}" if cursor else "?limit=2"
        page = client.get(f"{JOBS_URL}/{job_id}/certificates{query}").json()
        positions += [item["position"] for item in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert positions == [0, 1, 2, 3, 4]
    assert pages == 3


def test_invalid_cursor_is_a_client_error(client: TestClient) -> None:
    job_id = submit(client, job_payload(recipients("Ada Lovelace")))

    response = client.get(f"{JOBS_URL}/{job_id}/certificates?cursor=%%%")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"


def test_certificate_metadata(client: TestClient) -> None:
    job_id = submit(client, job_payload(recipients("Ada Lovelace")))
    certificate_id = certificate_items(client, job_id)[0]["certificate_id"]

    body = client.get(f"/api/v1/certificates/{certificate_id}").json()

    assert body["job_id"] == job_id
    assert body["status"] == "issued"
    assert body["attempts"] == 1
    assert body["issued_at"] is not None
    assert body["verification_code"]


# --- PDF download --------------------------------------------------------------------------


def test_pdf_download_returns_the_file_with_safe_headers(client: TestClient) -> None:
    payload = job_payload([{"name": "José Müller", "email": "jose@example.com"}])
    job_id = submit(client, payload)
    item = certificate_items(client, job_id)[0]

    response = client.get(str(item["download_url"]))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    disposition = response.headers["content-disposition"]
    assert f'filename="Jose_Muller_{item["serial"]}.pdf"' in disposition
    assert "filename*=UTF-8''Jos%C3%A9_M%C3%BCller_" in disposition


def test_pdf_filename_cannot_inject_headers_or_paths(client: TestClient) -> None:
    payload = job_payload([{"name": 'Evil"; ../../etc/passwd', "email": "e@example.com"}])
    item = certificate_items(client, submit(client, payload))[0]

    disposition = client.get(str(item["download_url"])).headers["content-disposition"]

    assert "/" not in disposition.split("filename*=")[0]
    assert disposition.count('"') == 2


def test_unknown_certificate_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/certificates/00000000-0000-0000-0000-000000000000/pdf")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CERTIFICATE_NOT_FOUND"


def test_rejected_certificate_has_no_pdf(client: TestClient) -> None:
    job_id = submit(client, job_payload([{"name": "", "email": "x@example.com"}]))
    certificate_id = certificate_items(client, job_id)[0]["certificate_id"]

    response = client.get(f"/api/v1/certificates/{certificate_id}/pdf")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "CERTIFICATE_NOT_ISSUED"
    assert error["details"] == [{"status": "rejected"}]


def test_failed_certificate_has_no_pdf(make_client: ClientFactory) -> None:
    client = make_client(renderer=FailingForRecipientRenderer("Ada Lovelace"))
    certificate_id = certificate_items(
        client, submit(client, job_payload(recipients("Ada Lovelace")))
    )[0]["certificate_id"]

    response = client.get(f"/api/v1/certificates/{certificate_id}/pdf")

    assert response.status_code == 404
    assert response.json()["error"]["details"] == [{"status": "failed"}]


# --- ZIP archive ---------------------------------------------------------------------------


def test_archive_contains_only_issued_pdfs_plus_a_full_manifest(
    make_client: ClientFactory,
) -> None:
    client = make_client(renderer=FailingForRecipientRenderer("Alan Turing"))
    payload = job_payload(
        [
            *recipients("Ada Lovelace", "Alan Turing", "Grace Hopper"),
            {"name": "", "email": "x@example.com"},
        ]
    )
    job_id = submit(client, payload)
    issued_serials = {
        item["serial"] for item in certificate_items(client, job_id) if item["status"] == "issued"
    }

    response = client.get(f"{JOBS_URL}/{job_id}/archive.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert archive.testzip() is None
    names = set(archive.namelist())
    assert names == {f"{serial}.pdf" for serial in issued_serials} | {"manifest.csv"}
    for serial in issued_serials:
        assert archive.read(f"{serial}.pdf").startswith(b"%PDF")

    manifest = list(csv.DictReader(io.StringIO(archive.read("manifest.csv").decode())))
    assert [(row["position"], row["status"]) for row in manifest] == [
        ("0", "issued"),
        ("1", "failed"),
        ("2", "issued"),
        ("3", "rejected"),
    ]
    assert manifest[1]["error_code"] == "RENDER_ERROR"
    assert manifest[3]["error_code"] == "NAME_BLANK"


def test_archive_manifest_neutralises_spreadsheet_formulas(client: TestClient) -> None:
    job_id = submit(client, job_payload([{"name": "=HYPERLINK(1)", "email": "f@example.com"}]))

    archive = zipfile.ZipFile(io.BytesIO(client.get(f"{JOBS_URL}/{job_id}/archive.zip").content))
    manifest = list(csv.DictReader(io.StringIO(archive.read("manifest.csv").decode())))
    assert manifest[0]["recipient_name"] == "'=HYPERLINK(1)"


def test_archive_for_unknown_job_is_404(client: TestClient) -> None:
    response = client.get(f"{JOBS_URL}/00000000-0000-0000-0000-000000000000/archive.zip")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- verification --------------------------------------------------------------------------


def test_verification_code_resolves_to_the_issued_certificate(client: TestClient) -> None:
    job_id = submit(client, job_payload(recipients("Ada Lovelace")))
    certificate_id = certificate_items(client, job_id)[0]["certificate_id"]
    code = client.get(f"/api/v1/certificates/{certificate_id}").json()["verification_code"]

    body = client.get(f"/api/v1/verify/{code}").json()

    assert body["valid"] is True
    assert body["recipient_name"] == "Ada Lovelace"
    assert body["title"] == "Advanced Data Engineering"
    assert "recipient_email" not in body


def test_verification_url_is_printed_into_the_certificate(make_client: ClientFactory) -> None:
    renderer = FakeRenderer()
    client = make_client(renderer=renderer)
    job_id = submit(client, job_payload(recipients("Ada Lovelace")))
    certificate_id = certificate_items(client, job_id)[0]["certificate_id"]
    code = client.get(f"/api/v1/certificates/{certificate_id}").json()["verification_code"]

    assert renderer.rendered[0].verification_url == f"http://testserver/api/v1/verify/{code}"


def test_unknown_verification_code_is_404(client: TestClient) -> None:
    response = client.get("/api/v1/verify/does-not-exist")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VERIFICATION_CODE_NOT_FOUND"


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "database": "ok"}
