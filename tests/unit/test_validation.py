from src.backend.validation import validate_messages


def test_valid_messages_are_returned():
    body = {"messages": [{"role": "user", "content": "hi", "extra": "ignored"}]}
    assert validate_messages(body) == [{"role": "user", "content": "hi"}]


def test_non_dict_body_is_rejected():
    assert validate_messages(["not", "a", "dict"]) is None


def test_missing_messages_is_rejected():
    assert validate_messages({}) is None


def test_empty_messages_is_rejected():
    assert validate_messages({"messages": []}) is None


def test_invalid_role_is_rejected():
    assert validate_messages({"messages": [{"role": "invalid", "content": "x"}]}) is None


def test_non_string_content_is_rejected():
    assert validate_messages({"messages": [{"role": "user", "content": 5}]}) is None
