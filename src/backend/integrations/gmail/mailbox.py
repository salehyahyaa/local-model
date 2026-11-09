"""Reads, organizes and sends Gmail over IMAP and SMTP, logged in with a Google app password."""

import imaplib
import re
import smtplib
from contextlib import contextmanager
from email import message_from_bytes, policy
from email.message import EmailMessage
from html.parser import HTMLParser

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
NETWORK_TIMEOUT = 20
MAX_MESSAGES = 50
DEFAULT_QUERY = "in:inbox"
SKIPPED_HTML_TAGS = {"script", "style", "head"}
HEADER_FIELDS = "BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)]"
ID_PATTERN = re.compile(r"^[0-9]+$")
UID_PATTERN = re.compile(rb"\bUID ([0-9]+)")
ALL_MAIL_PATTERN = re.compile(rb'\\All\b.*" ("[^"]+"|\S+)\s*$')


class GmailError(Exception):
    """A problem worth showing as-is: the message never contains the password."""


class GmailLoginError(GmailError):
    pass


def clean_app_password(password):
    """Google shows app passwords as four groups of letters; pasting them keeps the spaces."""
    return "".join(password.split())


def check_login(address, password):
    """Raises GmailLoginError if Gmail rejects the login, OSError if Gmail can't be reached."""
    connection = imaplib.IMAP4_SSL(IMAP_HOST, timeout=NETWORK_TIMEOUT)
    try:
        connection.login(address, password)
    except imaplib.IMAP4.error as error:
        raise GmailLoginError("Gmail rejected this address and app password.") from error
    finally:
        connection.shutdown()


@contextmanager
def open_all_mail(address, password, readonly=True):
    """Message ids are UIDs in All Mail, so an id from a search stays valid whichever label the message has."""
    connection = imaplib.IMAP4_SSL(IMAP_HOST, timeout=NETWORK_TIMEOUT)
    try:
        connection.login(address, password)
        status, _ = connection.select(find_all_mail_folder(connection), readonly=readonly)
        if status != "OK":
            raise GmailError("Could not open All Mail.")
        yield connection
    except imaplib.IMAP4.error as error:
        raise GmailError(f"Gmail refused the request: {error}") from error
    finally:
        connection.shutdown()


def find_all_mail_folder(connection):
    """The folder's name depends on the account's language, but it always carries the \\All flag."""
    _, folders = connection.list()
    for folder in folders:
        match = ALL_MAIL_PATTERN.search(folder) if isinstance(folder, bytes) else None
        if match:
            return match.group(1).decode()
    raise GmailError('All Mail is hidden from IMAP. Turn on "Show in IMAP" for it in Gmail\'s label settings.')


def clean_ids(ids):
    """Ids end up inside IMAP commands, so anything except plain numbers is rejected."""
    if isinstance(ids, (str, int)):
        ids = [ids]
    if not isinstance(ids, list) or not ids or len(ids) > MAX_MESSAGES:
        raise GmailError(f"Provide between 1 and {MAX_MESSAGES} message ids.")
    cleaned = [str(message_id).strip() for message_id in ids]
    if not all(ID_PATTERN.match(message_id) for message_id in cleaned):
        raise GmailError("Message ids must be the numbers returned by search_email.")
    return cleaned


def read_fetch_response(items):
    """Pairs each message's FETCH metadata with its content; Gmail may send FLAGS on either side of the content."""
    messages = []
    for item in items:
        if isinstance(item, tuple):
            messages.append({"metadata": item[0], "content": item[1]})
        elif isinstance(item, bytes) and messages:
            messages[-1]["metadata"] += item
    return messages


def fetch(connection, ids, parts):
    status, items = connection.uid("FETCH", ",".join(ids), f"(UID FLAGS {parts})")
    if status != "OK":
        raise GmailError("Could not fetch those messages.")
    return read_fetch_response(items)


def describe_headers(fetched):
    headers = message_from_bytes(fetched["content"], policy=policy.default)
    uid = UID_PATTERN.search(fetched["metadata"])
    return {
        "id": uid.group(1).decode() if uid else "",
        "from": str(headers["from"] or ""),
        "to": str(headers["to"] or ""),
        "subject": str(headers["subject"] or ""),
        "date": str(headers["date"] or ""),
        "message_id": str(headers["message-id"] or "").strip(),
        "unread": b"\\Seen" not in fetched["metadata"],
    }


def search(connection, query, limit):
    """query uses Gmail's search syntax. It goes as a literal, so quotes and any language are safe."""
    connection.literal = (" ".join(query.split()) or DEFAULT_QUERY).encode()
    status, data = connection.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
    if status != "OK":
        raise GmailError("Gmail could not run that search.")
    newest_first = [uid.decode() for uid in reversed(data[0].split())][:limit]
    if not newest_first:
        return []
    described = [describe_headers(item) for item in fetch(connection, newest_first, HEADER_FIELDS)]
    return sorted(described, key=lambda message: int(message["id"] or 0), reverse=True)


class HtmlTextReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_HTML_TAGS:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in SKIPPED_HTML_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "br", "tr", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(html):
    reader = HtmlTextReader()
    reader.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(reader.parts)).strip()


def read_body(message):
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except LookupError:  # the message declares a charset Python doesn't know
        text = part.get_payload(decode=True).decode("utf-8", "replace")
    return html_to_text(text) if part.get_content_type() == "text/html" else text.strip()


def describe_message(fetched):
    message = message_from_bytes(fetched["content"], policy=policy.default)
    attachments = [part.get_filename() or "unnamed" for part in message.iter_attachments()]
    return {**describe_headers(fetched), "attachments": attachments, "body": read_body(message)}


def read(connection, ids):
    """PEEK keeps the messages unread; marking them read is a separate choice."""
    return [describe_message(item) for item in fetch(connection, ids, "BODY.PEEK[]")]


def store(connection, ids, action, value):
    status, _ = connection.uid("STORE", ",".join(ids), action, value)
    if status != "OK":
        raise GmailError("Gmail could not update those messages.")


def mark_read(connection, ids, is_read):
    store(connection, ids, "+FLAGS" if is_read else "-FLAGS", "(\\Seen)")


def archive(connection, ids):
    store(connection, ids, "-X-GM-LABELS", "(\\Inbox)")


def trash(connection, ids):
    """Gmail keeps trashed messages for 30 days."""
    store(connection, ids, "+X-GM-LABELS", "(\\Trash)")


def build_message(address, to, subject, body, cc=""):
    message = EmailMessage()
    message["From"] = address
    message["To"] = to
    if cc:
        message["Cc"] = cc
    message["Subject"] = subject
    message.set_content(body)
    return message


def send(address, password, message):
    """Gmail files whatever it sends under Sent by itself."""
    with smtplib.SMTP_SSL(SMTP_HOST, timeout=NETWORK_TIMEOUT) as connection:
        connection.login(address, password)
        connection.send_message(message)
