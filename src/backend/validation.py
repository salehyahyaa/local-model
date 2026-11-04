ALLOWED_ROLES = {"user", "assistant", "system"}
MAX_MODEL_ID_LENGTH = 200


def is_valid_message(message):
    if not isinstance(message, dict):
        return False
    model = message.get("model")
    if model is not None and not is_valid_model_id(model):
        return False
    return message.get("role") in ALLOWED_ROLES and isinstance(message.get("content"), str)


def is_valid_model_id(model):
    return isinstance(model, str) and 0 < len(model) <= MAX_MODEL_ID_LENGTH


def validate_messages(body):
    if not isinstance(body, dict):
        return None
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    if not all(is_valid_message(message) for message in messages):
        return None
    return [{"role": message["role"], "content": message["content"]} for message in messages]


def validate_conversation_changes(body):
    """Allowed: title (non-empty str), isPinned (bool), isArchived (bool). Returns the changes or None."""
    if not isinstance(body, dict) or not body:
        return None
    changes = {}
    for key, value in body.items():
        if key == "title" and isinstance(value, str) and value.strip():
            changes[key] = value.strip()[:200]
        elif key in ("isPinned", "isArchived") and isinstance(value, bool):
            changes[key] = value
        else:
            return None
    return changes


def validate_settings_changes(body):
    """Allowed: theme ("light"/"dark"), sidebarCollapsed (bool), activeConversationId (int), selectedModel (str).

    Returns changes or None.
    """
    if not isinstance(body, dict) or not body:
        return None
    for key, value in body.items():
        if key == "theme" and value in ("light", "dark"):
            continue
        if key == "sidebarCollapsed" and isinstance(value, bool):
            continue
        if key == "activeConversationId" and isinstance(value, int) and not isinstance(value, bool):
            continue
        if key == "selectedModel" and is_valid_model_id(value):
            continue
        return None
    return dict(body)
