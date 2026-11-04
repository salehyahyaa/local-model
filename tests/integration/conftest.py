import os

import pytest

from tests.fixtures.fake_http_services import app as fake_http_app
from tests.helpers import BackgroundServer, reset_test_database

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.fixture
def test_database_url():
    if not TEST_DATABASE_URL:
        if os.getenv("CI"):
            pytest.fail("TEST_DATABASE_URL must be set in CI")
        pytest.skip("Set TEST_DATABASE_URL to a throwaway Postgres database to run database tests")
    reset_test_database(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def fake_http_services():
    server = BackgroundServer(fake_http_app)
    server.start()
    yield server.url
    server.stop()
