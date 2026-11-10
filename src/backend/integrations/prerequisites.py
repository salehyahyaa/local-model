"""The least information a tool needs from the owner before it may run, such as an event's title and time.

Any MCP tool can declare these in its definition, so no service needs its own wiring here:

    "_meta": {"prerequisites": [{"field": "summary", "name": "event title", "from_owner": true},
                                {"field": "start", "name": "time", "needs": "time", "from_owner": true}]}

With from_owner, the value must come from the owner's own messages: every word of a title, or a time they
wrote in any common way (see spoken_times).
The model can't fill it in by guessing. A tool missing any of them never runs and never reaches the approval card.
The model is told what's missing and asks the owner for it instead.
"""

import re

from src.backend.integrations.spoken_times import owner_said_time

PREREQUISITES_KEY = "prerequisites"
WORD = re.compile(r"[a-z0-9']+")


def owner_words(text):
    """Symbols people use in place of words count as those words, so "@ OPPC" matches "at OPPC"."""
    return set(WORD.findall(text.lower().replace("@", " at ").replace("&", " and ")))


class Prerequisite:
    """One piece of information, read from one argument."""

    def __init__(self, field, name, needs="text", from_owner=False):
        self.field = field
        self.name = name
        self.needs = needs
        self.from_owner = from_owner

    def is_given(self, arguments, owner_text="", now=None):
        value = arguments.get(self.field)
        if not isinstance(value, str) or not value.strip():
            return False
        if self.needs == "time":
            if self.from_owner:
                return owner_said_time(value, owner_text, now)
            # A date alone has no time of day, so it doesn't count.
            return re.search(r"T\d{2}:\d{2}", value) is not None
        if self.from_owner:
            words = WORD.findall(value.lower())
            return bool(words) and set(words) <= owner_words(owner_text)
        return True


class Prerequisites:
    """Everything one tool needs before it may run."""

    def __init__(self, items=()):
        self.items = list(items)

    @classmethod
    def from_tool(cls, tool):
        """Reads an MCP tool's declaration. Anything malformed is skipped, so a bad entry can't break the chat."""
        declared = (tool.get("_meta") or {}).get(PREREQUISITES_KEY) or []
        items = [
            Prerequisite(
                entry["field"],
                entry.get("name") or entry["field"],
                entry.get("needs", "text"),
                entry.get("from_owner") is True,
            )
            for entry in declared
            if isinstance(entry, dict) and isinstance(entry.get("field"), str)
        ]
        return cls(items)

    def missing(self, arguments, owner_text="", now=None):
        """The plain names of what the owner still needs to give, in order. owner_text is everything they wrote."""
        return [item.name for item in self.items if not item.is_given(arguments, owner_text, now)]

    def description(self):
        """Added to the tool's description, so the model asks before it ever tries the tool."""
        if not self.items:
            return ""
        names = ", ".join(item.name for item in self.items)
        return (
            f" Before using this, the owner must have given: {names}, in their own words. Use exactly what the "
            "owner said for these. If any is missing, ask the owner for it in one short question instead of guessing."
        )


def missing_message(missing):
    """The tool result the model gets instead of running the tool."""
    return (
        f"This did not happen, because the owner hasn't given: {', '.join(missing)} in their own words. Ask the "
        "owner for it in one short question, then use exactly what they say. Don't guess it."
    )
