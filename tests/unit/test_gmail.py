import asyncio
import imaplib
import json
import os
import smtplib

import pytest
from fastapi.testclient import TestClient

from src.backend import config
from src.backend.integrations import mcp_store, service, toolbox
from src.backend.integrations.errors import DuplicateNameError
from src.backend.integrations.gmail import mailbox, server
from src.backend.integrations.validation import validate_gmail_connection
from src.backend.main import app

client = TestClient(app)
PASSWORD_SECRET = "INTEGRATION_GMAIL_APP_PASSWORD"
CONNECTION = {"address": "me@gmail.com", "appPassword": "abcd efgh ijkl mnop"}


class FakeImap:
    """Records commands and answers the way Gmail does."""

    def __init__(self, fetch_items=None, search_result=b"", store_status="OK"):
        self.fetch_items = fetch_items or []
        self.search_result = search_result
        self.store_status = store_status
        self.commands = []
        self.literal = None

    def uid(self, command, *arguments):
        self.commands.append((command, arguments, self.literal))
        self.literal = None
        if command == "SEARCH":
            return "OK", [self.search_result]
        if command == "FETCH":
            return "OK", self.fetch_items
        return self.store_status, [b""]


HEADERS = (
    b"From: Amy <amy@example.com>\r\nTo: me@gmail.com\r\nSubject: Offer\r\n"
    b"Date: Thu, 05 Nov 2026 10:00:00 +0000\r\n\r\n"
)


@pytest.fixture
def fake_store(monkeypatch):
    saved = []

    async def create_server(record):
        if any(item["name"] == record["name"] for item in saved):
            raise DuplicateNameError(record["name"])
        created = {"id": len(saved) + 1, "enabled": True, "url": None, "headers": {}, **record}
        saved.append(created)
        return created

    async def delete_server(server_id):
        return saved.pop(server_id - 1)

    monkeypatch.setattr(mcp_store, "create_server", create_server)
    monkeypatch.setattr(mcp_store, "delete_server", delete_server)
    yield saved
    os.environ.pop(PASSWORD_SECRET, None)


def test_app_password_spaces_are_removed():
    assert mailbox.clean_app_password(" abcd efgh\tijkl mnop\n") == "abcdefghijklmnop"


@pytest.mark.parametrize(
    "body",
    [None, {}, {"address": "nope", "appPassword": "x"}, {"address": "a@b.com", "appPassword": " "},
     {"address": "a@b.com\r\nX: y", "appPassword": "x"}],
)
def test_invalid_connections_are_rejected(body):
    connection, error = validate_gmail_connection(body)
    assert connection is None
    assert error


def test_connect_verifies_login_and_keeps_password_out_of_the_database(fake_store, monkeypatch):
    logins = []
    monkeypatch.setattr(mailbox, "check_login", lambda address, password: logins.append((address, password)))

    created = asyncio.run(service.connect_gmail(CONNECTION))

    assert logins == [("me@gmail.com", "abcdefghijklmnop")]
    assert created["provider"] == "gmail"
    assert created["target"] == "me@gmail.com"
    assert fake_store[0]["env"]["GMAIL_APP_PASSWORD"] == "${" + PASSWORD_SECRET + "}"
    assert "abcdefghijklmnop" not in json.dumps(fake_store[0])
    assert os.environ[PASSWORD_SECRET] == "abcdefghijklmnop"


def test_rejected_login_saves_nothing(fake_store, monkeypatch):
    def reject(address, password):
        raise mailbox.GmailLoginError("no")

    monkeypatch.setattr(mailbox, "check_login", reject)
    response = client.post("/api/integrations/gmail", json=CONNECTION)

    assert response.status_code == 422
    assert "app password" in response.json()["error"]
    assert fake_store == []
    assert PASSWORD_SECRET not in os.environ


def test_unreachable_gmail_returns_502(fake_store, monkeypatch):
    def unreachable(address, password):
        raise OSError("no route")

    monkeypatch.setattr(mailbox, "check_login", unreachable)
    assert client.post("/api/integrations/gmail", json=CONNECTION).status_code == 502


def test_connecting_twice_returns_409_and_keeps_the_password(fake_store, monkeypatch):
    monkeypatch.setattr(mailbox, "check_login", lambda address, password: None)
    assert client.post("/api/integrations/gmail", json=CONNECTION).status_code == 201

    second = client.post("/api/integrations/gmail", json={"address": "b@gmail.com", "appPassword": "other"})

    assert second.status_code == 409
    assert os.environ[PASSWORD_SECRET] == "abcdefghijklmnop"


def test_removing_gmail_deletes_the_password(fake_store, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(mailbox, "check_login", lambda address, password: None)
    asyncio.run(service.connect_gmail(CONNECTION))

    assert asyncio.run(service.remove_mcp_server(1)) is True
    assert PASSWORD_SECRET not in os.environ


def test_all_mail_is_found_whatever_its_language():
    class Folders:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\All \\HasNoChildren) "/" "[Google Mail]/Alle Nachrichten"',
            ]

    assert mailbox.find_all_mail_folder(Folders()) == '"[Google Mail]/Alle Nachrichten"'


def test_hidden_all_mail_explains_the_fix():
    class Folders:
        def list(self):
            return "OK", [b'(\\HasNoChildren) "/" "INBOX"']

    with pytest.raises(mailbox.GmailError, match="Show in IMAP"):
        mailbox.find_all_mail_folder(Folders())


def test_search_sends_query_as_literal_and_returns_newest_first():
    items = [
        (b"1 (UID 5 FLAGS (\\Seen) BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {100}", HEADERS),
        b")",
        (b"2 (UID 9 BODY[HEADER.FIELDS (FROM TO SUBJECT DATE)] {100}", HEADERS),
        b" FLAGS ())",
    ]
    fake = FakeImap(fetch_items=items, search_result=b"3 5 9")

    results = mailbox.search(fake, 'from:"أمي"\r\nsubject:x', limit=2)

    command, arguments, literal = fake.commands[0]
    assert (command, arguments) == ("SEARCH", ("CHARSET", "UTF-8", "X-GM-RAW"))
    assert literal == 'from:"أمي" subject:x'.encode()
    assert fake.commands[1][1][0] == "9,5"
    assert [message["id"] for message in results] == ["9", "5"]
    assert results[0]["unread"] is True
    assert results[1]["unread"] is False
    assert results[1]["from"] == "Amy <amy@example.com>"


def test_empty_search_defaults_to_inbox_and_handles_no_results():
    fake = FakeImap()
    assert mailbox.search(fake, "  ", limit=5) == []
    assert fake.commands[0][2] == b"in:inbox"


def test_read_returns_text_and_attachment_names_without_marking_read():
    raw = (
        b"From: a@example.com\r\nSubject: Hi\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="b"\r\n\r\n'
        b"--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
        b"<html><head><style>p{}</style></head><body><p>Hello</p><script>bad()</script>there</body></html>\r\n"
        b'--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename="a.pdf"\r\n\r\nxx\r\n'
        b"--b--\r\n"
    )
    fake = FakeImap(fetch_items=[(b"1 (UID 7 FLAGS () BODY[] {10}", raw), b")"])

    [message] = mailbox.read(fake, ["7"])

    assert "BODY.PEEK[]" in fake.commands[0][1][1]
    assert message["id"] == "7"
    assert message["body"] == "Hello\nthere"
    assert message["attachments"] == ["a.pdf"]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (lambda fake: mailbox.mark_read(fake, ["1", "2"], True), ("1,2", "+FLAGS", "(\\Seen)")),
        (lambda fake: mailbox.mark_read(fake, ["1", "2"], False), ("1,2", "-FLAGS", "(\\Seen)")),
        (lambda fake: mailbox.archive(fake, ["1", "2"]), ("1,2", "-X-GM-LABELS", "(\\Inbox)")),
        (lambda fake: mailbox.trash(fake, ["1", "2"]), ("1,2", "+X-GM-LABELS", "(\\Trash)")),
    ],
)
def test_organize_actions_send_the_right_store(action, expected):
    fake = FakeImap()
    action(fake)
    assert fake.commands == [("STORE", expected, None)]


def test_failed_store_is_reported():
    with pytest.raises(mailbox.GmailError):
        mailbox.archive(FakeImap(store_status="NO"), ["1"])


@pytest.mark.parametrize("ids", [None, [], "1 OR 2", ["1:*"], ["1,2"], ["1"] * 51])
def test_unsafe_ids_are_rejected(ids):
    with pytest.raises(mailbox.GmailError):
        mailbox.clean_ids(ids)


def test_header_injection_in_send_is_refused(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "x")
    sent = []
    monkeypatch.setattr(mailbox, "send", lambda *arguments: sent.append(arguments))

    result = server.call_tool(
        {"name": "send_email", "arguments": {"to": "a@b.com", "subject": "x\r\nBcc: evil@b.com", "body": "y"}}
    )

    assert result["isError"] is True
    assert sent == []


def test_send_builds_the_message(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    sent = []
    monkeypatch.setattr(mailbox, "send", lambda *arguments: sent.append(arguments))

    result = server.call_tool(
        {"name": "send_email", "arguments": {"to": "a@b.com", "cc": "c@b.com", "subject": "Hi", "body": "Yo"}}
    )

    assert "isError" not in result
    address, password, message = sent[0]
    assert (address, password) == ("me@gmail.com", "secret")
    assert (message["From"], message["To"], message["Cc"], message["Subject"]) == (
        "me@gmail.com", "a@b.com", "c@b.com", "Hi")
    assert message.get_content().strip() == "Yo"


@pytest.mark.parametrize(
    "error",
    [smtplib.SMTPException("bad"), imaplib.IMAP4.error("bad"), OSError("bad"), mailbox.GmailError("bad")],
)
def test_tool_failures_become_tool_errors(monkeypatch, error):
    def fail(arguments):
        raise error

    monkeypatch.setitem(server.HANDLERS, "search_email", fail)
    result = server.call_tool({"name": "search_email", "arguments": {}})
    assert result["isError"] is True
    assert "bad" in result["content"][0]["text"]


def test_notifications_get_no_response():
    assert server.handle_line('{"jsonrpc": "2.0", "method": "notifications/initialized"}') is None
    assert server.handle_line("not json") is None


def test_real_integration_plumbing_starts_the_server_and_lists_tools(fake_store, monkeypatch):
    """Goes through the same subprocess and MCP session path a model's tool call uses; no network is touched."""
    monkeypatch.setattr(mailbox, "check_login", lambda address, password: None)
    monkeypatch.setenv("PYTHONPATH", "")
    asyncio.run(service.connect_gmail(CONNECTION))

    async def run():
        async with toolbox.open_toolbox(fake_store, []) as tools:
            names = {definition["function"]["name"] for definition in tools.definitions}
            _, bad_ids = await tools.call("Gmail__read_email", {"ids": ["1:*"]})
            return names, bad_ids

    names, bad_ids = asyncio.run(run())

    assert names == {
        "Gmail__search_email", "Gmail__read_email", "Gmail__mark_email",
        "Gmail__archive_email", "Gmail__trash_email", "Gmail__send_email",
    }
    assert bad_ids.startswith("Error: Message ids must be")
