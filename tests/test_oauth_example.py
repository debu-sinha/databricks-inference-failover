"""Check deferred credential mapping without requesting real OAuth tokens."""

import importlib.util
from pathlib import Path

import pytest


def load_example():
    path = Path(__file__).parents[1] / "examples" / "application_oauth.py"
    spec = importlib.util.spec_from_file_location("oauth_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_destination_credentials_are_deferred_and_isolated(monkeypatch):
    module = load_example()
    seen = []
    auth_calls = []

    class FakeConfig:
        def __init__(self, settings):
            self.settings = settings

        def authenticate(self):
            auth_calls.append(self.settings["host"])
            return {"Authorization": "Bearer refreshed-token"}

    def builder(**settings):
        seen.append(settings)
        return FakeConfig(settings)

    routes = []
    for prefix, number in [("PRIMARY", "1"), ("BACKUP", "2")]:
        monkeypatch.setenv(
            prefix + "_WORKSPACE_URL", f"https://adb-{number}.1.azuredatabricks.net"
        )
        monkeypatch.setenv(prefix + "_SERVICE", "demo.ai.model")
        monkeypatch.delenv(prefix + "_CLIENT_ID", raising=False)
        monkeypatch.delenv(prefix + "_CLIENT_SECRET", raising=False)
        routes.append(module.destination(prefix, builder=builder))
    assert seen == []
    for prefix in ["PRIMARY", "BACKUP"]:
        monkeypatch.setenv(prefix + "_CLIENT_ID", prefix + "-id")
        monkeypatch.setenv(prefix + "_CLIENT_SECRET", prefix + "-secret")
    for route in routes:
        assert route.token_provider() == "refreshed-token"
        assert route.token_provider() == "refreshed-token"
    assert len(seen) == 2
    assert len(auth_calls) == 4
    assert seen[0]["client_id"] == "PRIMARY-id"
    assert seen[1]["client_id"] == "BACKUP-id"
    assert seen[0]["client_secret"] == "PRIMARY-secret"
    assert seen[1]["client_secret"] == "BACKUP-secret"
    assert seen[0]["host"] != seen[1]["host"]
    assert all(settings["auth_type"] == "oauth-m2m" for settings in seen)


@pytest.mark.parametrize("header", ["", "Basic secret", "Bearer ", "Bearer"])
def test_rejects_non_bearer_headers(monkeypatch, header):
    module = load_example()
    for key, value in {
        "PRIMARY_WORKSPACE_URL": "https://adb-1.1.azuredatabricks.net",
        "PRIMARY_SERVICE": "demo.ai.model",
        "PRIMARY_CLIENT_ID": "client",
        "PRIMARY_CLIENT_SECRET": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    class FakeConfig:
        def authenticate(self):
            return {"Authorization": header}

    route = module.destination("PRIMARY", builder=lambda **settings: FakeConfig())
    with pytest.raises(ValueError, match="bearer"):
        route.token_provider()
