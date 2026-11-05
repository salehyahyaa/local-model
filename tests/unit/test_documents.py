import pytest
from fastapi.testclient import TestClient

from src.backend.attachments import documents
from src.backend.main import app

client = TestClient(app)

VALID_PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def upload(content=VALID_PDF, content_type="application/pdf", file_name="report.pdf", message_id=1):
    return client.post(
        f"/api/messages/{message_id}/documents",
        content=content,
        headers={"Content-Type": content_type, "X-File-Name": file_name},
    )


def test_valid_pdf_passes_check():
    documents.check_pdf(VALID_PDF)


@pytest.mark.parametrize(
    "content, problem",
    [
        (b"", "empty"),
        (b"MZ\x90\x00 not a pdf %%EOF", "valid PDF"),
        (b"%PDF-1.7\ncut off before the end", "valid PDF"),
    ],
)
def test_invalid_pdfs_are_rejected(content, problem):
    with pytest.raises(documents.InvalidDocumentError, match=problem):
        documents.check_pdf(content)


def test_oversized_pdf_is_rejected(monkeypatch):
    monkeypatch.setattr(documents, "MAX_DOCUMENT_BYTES", 10)
    with pytest.raises(documents.InvalidDocumentError, match="up to"):
        documents.check_pdf(VALID_PDF)


@pytest.mark.parametrize(
    "raw_name, cleaned",
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd.pdf"),
        ("a\x00b<c>.PDF", "a_b_c_.PDF"),
        ("", "document.pdf"),
        ("x" * 400 + ".pdf", "x" * 251 + ".pdf"),
    ],
)
def test_file_names_are_cleaned(raw_name, cleaned):
    assert documents.clean_file_name(raw_name) == cleaned


def test_storage_keys_cannot_escape_the_upload_folder():
    with pytest.raises(ValueError):
        documents.storage_path("../secrets.pdf")


def test_upload_rejects_other_file_types():
    response = upload(content_type="application/x-msdownload")
    assert response.status_code == 415


def test_upload_rejects_oversized_body_before_reading(monkeypatch):
    from src.backend.attachments import routes

    monkeypatch.setattr(routes, "MAX_DOCUMENT_BYTES", 5)
    assert upload().status_code == 413


def test_upload_rejects_fake_pdf(monkeypatch):
    response = upload(content=b"just text pretending to be a pdf")
    assert response.status_code == 422
    assert response.json() == {"error": "That file isn't a valid PDF."}


def test_upload_saves_document(monkeypatch):
    calls = []

    async def fake_add_document(message_id, file_name, content):
        calls.append((message_id, file_name, content))
        return {"id": 9, "fileName": file_name, "sizeBytes": len(content)}

    monkeypatch.setattr(documents, "add_document", fake_add_document)
    response = upload(file_name="My%20Report.pdf", message_id=4)
    assert response.status_code == 201
    assert response.json() == {"id": 9, "fileName": "My Report.pdf", "sizeBytes": len(VALID_PDF)}
    assert calls == [(4, "My Report.pdf", VALID_PDF)]


def test_upload_to_someone_elses_message_is_not_found(monkeypatch):
    async def fake_add_document(message_id, file_name, content):
        return None

    monkeypatch.setattr(documents, "add_document", fake_add_document)
    assert upload().status_code == 404


def test_download_of_unknown_document_is_not_found(monkeypatch):
    async def fake_find_document(document_id):
        return None

    monkeypatch.setattr(documents, "find_document", fake_find_document)
    assert client.get("/api/documents/1").status_code == 404


def test_download_serves_pdf_safely(monkeypatch, tmp_path):
    path = tmp_path / "abc.pdf"
    path.write_bytes(VALID_PDF)

    async def fake_find_document(document_id):
        return path, "report.pdf"

    monkeypatch.setattr(documents, "find_document", fake_find_document)
    response = client.get("/api/documents/1")
    assert response.status_code == 200
    assert response.content == VALID_PDF
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("inline")
