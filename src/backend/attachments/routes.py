from urllib.parse import unquote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from src.backend.attachments import documents
from src.backend.config import MAX_DOCUMENT_BYTES

router = APIRouter(prefix="/api")


@router.post("/messages/{message_id}/documents", status_code=201)
async def add_document(message_id: int, request: Request):
    """Body is the raw PDF; the file name comes URL-encoded in the X-File-Name header."""
    if request.headers.get("content-type", "").split(";")[0].strip() != documents.PDF_CONTENT_TYPE:
        return JSONResponse({"error": "Only PDF documents can be uploaded."}, status_code=415)
    declared_size = request.headers.get("content-length", "")
    if declared_size.isdigit() and int(declared_size) > MAX_DOCUMENT_BYTES:
        return JSONResponse({"error": f"PDFs can be up to {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB."}, status_code=413)

    file_name = unquote(request.headers.get("x-file-name", ""))
    try:
        document = await documents.add_document(message_id, file_name, await request.body())
    except documents.InvalidDocumentError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    if document is None:
        return JSONResponse({"error": "Message not found"}, status_code=404)
    return document


@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    found = await documents.find_document(document_id)
    if found is None or not found[0].exists():
        return JSONResponse({"error": "Document not found"}, status_code=404)
    path, file_name = found
    return FileResponse(
        path,
        media_type=documents.PDF_CONTENT_TYPE,
        filename=file_name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
