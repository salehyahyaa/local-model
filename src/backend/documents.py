"""PDF documents attached to messages: checked, stored on disk, and recorded in message_documents."""

import hashlib
import logging
import os
import re
import time
import uuid

from src.backend import db
from src.backend.config import MAX_DOCUMENT_BYTES, UPLOAD_DIR

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"
STORAGE_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}\.pdf$")
UNSAFE_NAME_CHARACTERS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


class InvalidDocumentError(Exception):
    """The upload isn't a PDF we accept; the message is safe to show the user."""


def clean_file_name(raw_name):
    name = UNSAFE_NAME_CHARACTERS.sub("_", os.path.basename(raw_name or "")).strip(" .")
    if not name:
        name = "document"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[-255:]


def check_pdf(content):
    if not content:
        raise InvalidDocumentError("The file is empty.")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise InvalidDocumentError(f"PDFs can be up to {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB.")
    # Real PDFs start with the %PDF- header (allowed within the first 1 KB) and end with %%EOF.
    if b"%PDF-" not in content[:1024] or b"%%EOF" not in content[-2048:]:
        raise InvalidDocumentError("That file isn't a valid PDF.")


def storage_path(storage_key):
    if not STORAGE_KEY_PATTERN.match(storage_key):
        raise ValueError(f"Bad storage key: {storage_key!r}")
    return UPLOAD_DIR / storage_key


def write_file(content):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_key = f"{uuid.uuid4().hex}.pdf"
    path = storage_path(storage_key)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(content)
    return storage_key


def delete_files(storage_keys):
    for storage_key in storage_keys:
        try:
            storage_path(storage_key).unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.exception("Could not delete stored document %s", storage_key)


def public_document(row):
    return {"id": row["id"], "fileName": row["file_name"], "sizeBytes": row["size_bytes"]}


async def add_document(message_id, raw_file_name, content):
    """Returns the saved document, or None if the message isn't one of the user's. Raises InvalidDocumentError."""
    check_pdf(content)
    pool = db.require_pool()
    owns_message = await pool.fetchval(
        """SELECT EXISTS (SELECT 1 FROM messages m JOIN conversations c ON c.id = m.conversation_id
                          WHERE m.id = $1 AND c.user_id = $2)""",
        message_id,
        db.user_id,
    )
    if not owns_message:
        return None

    storage_key = write_file(content)
    try:
        row = await pool.fetchrow(
            """INSERT INTO message_documents (message_id, file_name, content_type, size_bytes, sha256, storage_key)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, file_name, size_bytes""",
            message_id,
            clean_file_name(raw_file_name),
            PDF_CONTENT_TYPE,
            len(content),
            hashlib.sha256(content).hexdigest(),
            storage_key,
        )
    except Exception:
        delete_files([storage_key])
        raise
    logger.info("Stored document %s (%d bytes) for message %s", row["id"], len(content), message_id)
    return public_document(row)


async def find_document(document_id):
    """Returns (path, file_name) for one of the user's documents, or None."""
    pool = db.require_pool()
    row = await pool.fetchrow(
        """SELECT d.file_name, d.storage_key FROM message_documents d
           JOIN messages m ON m.id = d.message_id JOIN conversations c ON c.id = m.conversation_id
           WHERE d.id = $1 AND c.user_id = $2""",
        document_id,
        db.user_id,
    )
    if row is None:
        return None
    return storage_path(row["storage_key"]), row["file_name"]


async def documents_by_message(connection, user_id):
    rows = await connection.fetch(
        """SELECT d.id, d.message_id, d.file_name, d.size_bytes FROM message_documents d
           JOIN messages m ON m.id = d.message_id JOIN conversations c ON c.id = m.conversation_id
           WHERE c.user_id = $1 ORDER BY d.id""",
        user_id,
    )
    grouped = {}
    for row in rows:
        grouped.setdefault(row["message_id"], []).append(public_document(row))
    return grouped


async def storage_keys_in_conversation(conversation_id):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT d.storage_key FROM message_documents d JOIN messages m ON m.id = d.message_id
           JOIN conversations c ON c.id = m.conversation_id WHERE c.id = $1 AND c.user_id = $2""",
        conversation_id,
        db.user_id,
    )
    return [row["storage_key"] for row in rows]


async def storage_keys_of_last_message(conversation_id):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT d.storage_key FROM message_documents d WHERE d.message_id = (
               SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE m.conversation_id = $1 AND c.user_id = $2 ORDER BY m.id DESC LIMIT 1)""",
        conversation_id,
        db.user_id,
    )
    return [row["storage_key"] for row in rows]


ORPHAN_MIN_AGE_SECONDS = 3600


async def delete_orphaned_files():
    """Deletes stored PDFs that no database row points to (e.g. left behind by a crash). Skips files under
    an hour old, since an upload writes its file just before saving its row."""
    if not UPLOAD_DIR.exists():
        return 0
    pool = db.require_pool()
    known_keys = {row["storage_key"] for row in await pool.fetch("SELECT storage_key FROM message_documents")}
    cutoff = time.time() - ORPHAN_MIN_AGE_SECONDS
    orphaned = [
        path.name
        for path in UPLOAD_DIR.iterdir()
        if STORAGE_KEY_PATTERN.match(path.name) and path.name not in known_keys and path.stat().st_mtime < cutoff
    ]
    delete_files(orphaned)
    if orphaned:
        logger.info("Deleted %d orphaned document file(s)", len(orphaned))
    return len(orphaned)
