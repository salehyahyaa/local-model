"""PDF uploads against a real database: saving, and permanent deletion of rows and files."""

import asyncio
import os
import time

import pytest

from src.backend import db, documents, store

VALID_PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "UPLOAD_DIR", tmp_path)
    return tmp_path


def run_with_database(database_url, monkeypatch, scenario):
    monkeypatch.setattr(db, "DATABASE_URL", database_url)

    async def run():
        await db.connect()
        try:
            return await scenario()
        finally:
            await db.disconnect()

    return asyncio.run(run())


async def count_rows(table):
    return await db.pool.fetchval(f"SELECT count(*) FROM {table}")


def test_document_is_saved_and_listed(test_database_url, monkeypatch, upload_dir):
    async def scenario():
        conversation = await store.create_conversation()
        message_id = await store.add_message(conversation["id"], "user", "see attached")
        document = await documents.add_document(message_id, "Report.pdf", VALID_PDF)
        found_path, found_name = await documents.find_document(document["id"])
        return document, found_path, found_name, await store.get_state()

    document, path, name, state = run_with_database(test_database_url, monkeypatch, scenario)
    assert document == {"id": document["id"], "fileName": "Report.pdf", "sizeBytes": len(VALID_PDF)}
    assert path.read_bytes() == VALID_PDF
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert name == "Report.pdf"
    assert state["conversations"][0]["messages"][0]["documents"] == [document]


def test_upload_to_missing_message_stores_nothing(test_database_url, monkeypatch, upload_dir):
    async def scenario():
        return await documents.add_document(999999, "x.pdf", VALID_PDF)

    assert run_with_database(test_database_url, monkeypatch, scenario) is None
    assert list(upload_dir.iterdir()) == []


def test_deleting_conversation_permanently_deletes_messages_documents_and_files(
    test_database_url, monkeypatch, upload_dir
):
    async def scenario():
        conversation = await store.create_conversation()
        message_id = await store.add_message(conversation["id"], "user", "private notes")
        await documents.add_document(message_id, "a.pdf", VALID_PDF)
        await documents.add_document(message_id, "b.pdf", VALID_PDF)
        keys = await documents.storage_keys_in_conversation(conversation["id"])
        assert await store.delete_conversation(conversation["id"])
        documents.delete_files(keys)
        return [await count_rows(table) for table in ("conversations", "messages", "message_documents")]

    assert run_with_database(test_database_url, monkeypatch, scenario) == [0, 0, 0]
    assert list(upload_dir.iterdir()) == []


def test_deleting_last_message_permanently_deletes_its_documents(test_database_url, monkeypatch, upload_dir):
    async def scenario():
        conversation = await store.create_conversation()
        await store.add_message(conversation["id"], "user", "keep me")
        message_id = await store.add_message(conversation["id"], "user", "delete me")
        await documents.add_document(message_id, "a.pdf", VALID_PDF)
        keys = await documents.storage_keys_of_last_message(conversation["id"])
        assert await store.delete_last_message(conversation["id"])
        documents.delete_files(keys)
        contents = [row["content"] for row in await db.pool.fetch("SELECT content FROM messages")]
        return contents, await count_rows("message_documents")

    assert run_with_database(test_database_url, monkeypatch, scenario) == (["keep me"], 0)
    assert list(upload_dir.iterdir()) == []


def test_orphaned_files_are_cleaned_up(test_database_url, monkeypatch, upload_dir):
    old = time.time() - 2 * documents.ORPHAN_MIN_AGE_SECONDS
    orphan = upload_dir / ("a" * 32 + ".pdf")
    orphan.write_bytes(VALID_PDF)
    os.utime(orphan, (old, old))
    recent = upload_dir / ("b" * 32 + ".pdf")
    recent.write_bytes(VALID_PDF)

    async def scenario():
        conversation = await store.create_conversation()
        message_id = await store.add_message(conversation["id"], "user", "x")
        kept = await documents.add_document(message_id, "kept.pdf", VALID_PDF)
        return kept, await documents.delete_orphaned_files()

    kept, deleted_count = run_with_database(test_database_url, monkeypatch, scenario)
    assert deleted_count == 1
    assert not orphan.exists()
    assert recent.exists()
    assert len(list(upload_dir.iterdir())) == 2
