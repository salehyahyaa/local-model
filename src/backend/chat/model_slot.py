"""Where the chat model plugs in. It stays empty until the owner explicitly chooses one (see CLAUDE.md).

A model is any object with this method:

    async def stream(self, messages, tools):
        yield {"type": "text", "text": "..."}
        yield {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}

messages and tools use the OpenAI chat format, which most model servers accept. Raise ModelError on failure.
"""

connected_model = None


class ModelError(Exception):
    """Its text is shown in the chat."""
