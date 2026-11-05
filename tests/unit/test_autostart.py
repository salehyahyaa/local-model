import plistlib
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.autostart import service
from src.backend.autostart.routes import router
from src.backend.config import ROOT_DIR

BOT = "com.localmodel.telegram-bot"


class FakeLaunchctl:
    def __init__(self, print_output="state = running\n", exit_code=0):
        self.print_output = print_output
        self.exit_code = exit_code
        self.calls = []

    def __call__(self, *arguments):
        self.calls.append(arguments)
        output = self.print_output if arguments[0] == "print" else ""
        return subprocess.CompletedProcess(arguments, self.exit_code, stdout=output, stderr="")

    def commands(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def launchctl(tmp_path, monkeypatch):
    fake = FakeLaunchctl()
    monkeypatch.setattr(service, "LAUNCH_AGENTS_DIR", tmp_path)
    monkeypatch.setattr(service, "run_launchctl", fake)
    return fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_install_writes_a_valid_service_and_loads_it(launchctl, tmp_path):
    service.install(BOT, "/project/venv/bin/python")
    settings = plistlib.loads((tmp_path / f"{BOT}.plist").read_bytes())
    assert settings["Label"] == BOT
    assert settings["ProgramArguments"] == ["/project/venv/bin/python", "-m", "src.backend.telegram_bot"]
    assert settings["WorkingDirectory"] == str(ROOT_DIR)
    assert settings["RunAtLoad"] is True
    assert settings["KeepAlive"] is True
    assert launchctl.commands() == ["bootout", "bootstrap"]


def test_install_reports_when_macos_refuses(launchctl):
    launchctl.exit_code = 5
    with pytest.raises(service.AutostartError):
        service.install(BOT, "/python")


def test_app_binds_to_this_computer_only():
    assert service.PROGRAMS[service.APP_LABEL]["arguments"][-2:] == ["--host", "127.0.0.1"]


def test_lists_only_installed_programs(launchctl, client):
    assert client.get("/api/autostart").json() == {"programs": []}
    service.install(BOT, "/python")
    assert client.get("/api/autostart").json() == {
        "programs": [{"id": BOT, "name": "Telegram bot", "isRunning": True, "isThisApp": False}]
    }


def test_unrelated_files_in_the_folder_are_not_listed(launchctl, client, tmp_path):
    (tmp_path / "homebrew.mxcl.postgresql@14.plist").write_bytes(b"")
    assert client.get("/api/autostart").json() == {"programs": []}


def test_shows_when_a_program_is_not_running(launchctl, client):
    service.install(BOT, "/python")
    launchctl.print_output = "state = waiting\n"
    assert client.get("/api/autostart").json()["programs"][0]["isRunning"] is False


def test_nested_state_lines_do_not_count_as_running(launchctl):
    launchctl.print_output = "state = waiting\n\tsubsystem = {\n\t\tvalue = state = running\n\t}\n"
    assert service.is_running(BOT) is False


def test_status_is_false_when_launchctl_is_missing(monkeypatch):
    def missing(*arguments):
        raise FileNotFoundError

    monkeypatch.setattr(service, "run_launchctl", missing)
    assert service.is_running(BOT) is False


def test_remove_deletes_the_file_and_stops_the_program(launchctl, client, tmp_path):
    service.install(BOT, "/python")
    launchctl.calls.clear()
    response = client.delete(f"/api/autostart/{BOT}")
    assert response.status_code == 200
    assert not (tmp_path / f"{BOT}.plist").exists()
    assert launchctl.commands() == ["bootout"]
    assert client.get("/api/autostart").json() == {"programs": []}


def test_removing_a_program_that_is_not_installed_is_a_404(launchctl, client):
    assert client.delete(f"/api/autostart/{BOT}").status_code == 404
    assert launchctl.calls == []


@pytest.mark.parametrize("label", ["homebrew.mxcl.postgresql@14", "com.localmodel.other", "..%2F..%2Fevil"])
def test_cannot_remove_anything_else_on_the_mac(launchctl, client, tmp_path, label):
    other = tmp_path / "homebrew.mxcl.postgresql@14.plist"
    other.write_bytes(b"keep me")
    assert client.delete(f"/api/autostart/{label}").status_code == 404
    assert other.read_bytes() == b"keep me"
    assert launchctl.calls == []


def test_stop_ignores_a_program_that_is_not_loaded(launchctl, caplog):
    launchctl.exit_code = service.NOT_LOADED_EXIT_CODE
    service.stop(BOT)
    assert caplog.text == ""
