import os

import pytest
from dotenv import dotenv_values

from src.backend import config
from src.backend.integrations import env_secrets


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text('EXISTING_KEY="keep me"\n')
    monkeypatch.setattr(config, "ENV_FILE", path)
    yield path
    for name in list(os.environ):
        if name.startswith("INTEGRATION_TEST_"):
            del os.environ[name]


def test_secret_name_is_upper_snake_case():
    assert env_secrets.secret_name("My Weather-API", "api key") == "INTEGRATION_MY_WEATHER_API_API_KEY"


def test_save_secret_never_writes_env_file(env_file):
    env_secrets.save_secret("INTEGRATION_TEST_KEY", "value with spaces")
    assert dotenv_values(env_file) == {"EXISTING_KEY": "keep me"}
    assert env_secrets.secret_exists("INTEGRATION_TEST_KEY")
    assert env_secrets.resolve("${INTEGRATION_TEST_KEY}") == "value with spaces"


def test_remove_secret_deletes_it(env_file):
    env_secrets.save_secret("INTEGRATION_TEST_KEY", "abc")
    env_secrets.remove_secret("INTEGRATION_TEST_KEY")
    assert not env_secrets.secret_exists("INTEGRATION_TEST_KEY")


def test_remove_secret_cleans_up_old_env_file_entries(env_file, monkeypatch):
    env_file.write_text('EXISTING_KEY="keep me"\nINTEGRATION_TEST_OLD="old"\n')
    monkeypatch.setenv("INTEGRATION_TEST_OLD", "old")
    env_secrets.remove_secret("INTEGRATION_TEST_OLD")
    assert dotenv_values(env_file) == {"EXISTING_KEY": "keep me"}
    assert "INTEGRATION_TEST_OLD" not in os.environ


def test_remove_secret_never_touches_keys_it_did_not_create(env_file):
    env_secrets.remove_secret("EXISTING_KEY")
    assert dotenv_values(env_file) == {"EXISTING_KEY": "keep me"}


def test_resolve_replaces_references(env_file, monkeypatch):
    monkeypatch.setenv("INTEGRATION_TEST_TOKEN", "t0k3n")
    assert env_secrets.resolve("Bearer ${INTEGRATION_TEST_TOKEN}") == "Bearer t0k3n"
    assert env_secrets.resolve("${INTEGRATION_TEST_MISSING}") == ""


def test_find_references():
    mapping = {"Authorization": "Bearer ${INTEGRATION_A_API_KEY}", "X-Other": "${INTEGRATION_B_TOKEN} plain"}
    assert env_secrets.find_references(mapping) == {"INTEGRATION_A_API_KEY", "INTEGRATION_B_TOKEN"}
