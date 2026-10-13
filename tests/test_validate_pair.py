import importlib.util
import json
from pathlib import Path

import pytest

from inference_failover import WireResponse

MODULE_PATH = Path(__file__).parents[1] / "examples" / "validate_pair.py"
spec = importlib.util.spec_from_file_location("validate_pair", MODULE_PATH)
validate_pair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_pair)


@pytest.fixture
def configured(monkeypatch):
    for prefix, number in (("PRIMARY", "100"), ("BACKUP", "200")):
        monkeypatch.setenv(
            f"{prefix}_WORKSPACE_URL", f"https://adb-{number}.1.azuredatabricks.net"
        )
        monkeypatch.setenv(f"{prefix}_SERVICE", f"demo.ai.{prefix.lower()}")
        monkeypatch.setenv(f"{prefix}_TOKEN", f"{prefix}-synthetic-token")


def test_preview_never_resolves_config_or_credentials(monkeypatch, capsys):
    def fail(_prefix):
        raise AssertionError("preview touched configuration")

    monkeypatch.setattr(validate_pair, "destination", fail)
    assert validate_pair.main([]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["credentials_read"] is False
    assert receipt["maximum_live_inference_attempts"] == 4


@pytest.mark.parametrize(
    "baselines_only,expected_live,expected_cases", [(True, 2, 2), (False, 4, 4)]
)
def test_explicit_run_has_bounded_real_calls(
    configured, monkeypatch, capsys, baselines_only, expected_live, expected_cases
):
    import inference_failover.client as client_module

    calls = []

    def send(self, target, token, payload, timeout):
        request = json.loads(payload)
        calls.append((target.name, token, request))
        return WireResponse(
            200,
            json.dumps(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {"type": "output_text", "text": "PRIVATE_OUTPUT"}
                            ],
                        }
                    ],
                }
            ).encode(),
        )

    monkeypatch.setattr(client_module.HttpTransport, "send", send)
    args = ["--execute"] + (["--baselines-only"] if baselines_only else [])
    assert validate_pair.main(args) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert len(calls) == expected_live
    assert len(result["cases"]) == expected_cases
    assert all(call[2]["max_output_tokens"] == 64 for call in calls)
    assert "synthetic-token" not in output
    assert "PRIVATE_OUTPUT" not in output
    assert "demo.ai" not in output
    assert "Reply with READY" not in output
    if not baselines_only:
        assert [call[0] for call in calls] == ["primary", "backup", "backup", "primary"]
        assert result["cases"][2]["attempts"][0]["synthetic"] is True
        assert calls[2][1] == "BACKUP-synthetic-token"


def test_existing_receipt_stops_before_inference(
    configured, monkeypatch, tmp_path, capsys
):
    target = tmp_path / "receipt.json"
    target.write_text("preserve")

    def fail(*args, **kwargs):
        raise AssertionError("inference should not start")

    monkeypatch.setattr(validate_pair, "run_case", fail)
    assert validate_pair.main(["--execute", "--receipt", str(target)]) == 2
    assert target.read_text() == "preserve"
    assert "No inference started" in capsys.readouterr().out


def test_receipt_is_private_and_sanitized(configured, monkeypatch, tmp_path, capsys):
    import stat

    target = tmp_path / "new-receipt.json"

    def case(label, client, *, synthetic_primary=False):
        client.close()
        return {"case": label, "result": "completed", "attempts": []}

    monkeypatch.setattr(validate_pair, "run_case", case)
    assert (
        validate_pair.main(["--execute", "--baselines-only", "--receipt", str(target)])
        == 0
    )
    saved = json.loads(target.read_text())
    assert len(saved["cases"]) == 2
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert "synthetic-token" not in target.read_text()
    assert "demo.ai" not in capsys.readouterr().out


def test_failed_baseline_skips_optional_cases(configured, monkeypatch, capsys):
    import inference_failover.client as client_module

    calls = []

    def send(self, target, token, payload, timeout):
        calls.append(target.name)
        return WireResponse(403, b"")

    monkeypatch.setattr(client_module.HttpTransport, "send", send)
    assert validate_pair.main(["--execute"]) == 1
    assert calls == ["primary", "backup"]
    assert len(json.loads(capsys.readouterr().out)["cases"]) == 2
