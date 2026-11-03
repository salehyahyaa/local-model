ALLOWED_ROLES = {"user", "assistant", "system"}


def is_valid_message(message):
    if not isinstance(message, dict):
        return False
    return message.get("role") in ALLOWED_ROLES and isinstance(message.get("content"), str)


def validate_messages(body):
    if not isinstance(body, dict):
        return None
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    if not all(is_valid_message(message) for message in messages):
        return None
    return [{"role": message["role"], "content": message["content"]} for message in messages]
