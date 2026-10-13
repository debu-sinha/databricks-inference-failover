import json
import time

import pytest

from inference_failover import (
    Destination,
    FailoverClient,
    FailoverError,
    Policy,
    TransportError,
    WireResponse,
)
from inference_failover.client import MAX_BODY_BYTES


def completed(text="READY"):
    return json.dumps(
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text}],
                }
            ],
        }
    ).encode()


def dest(name="primary", callback=lambda: "synthetic-token"):
    number = 100 if name == "primary" else 200
    return Destination(
        name, f"https://adb-{number}.1.azuredatabricks.net", f"demo.ai.{name}", callback
    )


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def send(self, destination, token, payload, timeout):
        self.calls.append((destination.name, token, json.loads(payload), timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


def test_primary_only_and_refresh_callback():
    tokens = iter(["first", "second"])
    wire = FakeTransport(
        [WireResponse(200, completed()), WireResponse(200, completed())]
    )
    with FailoverClient(
        dest(callback=lambda: next(tokens)), dest("backup"), transport=wire
    ) as client:
        first = client.generate("Hello")
        second = client.generate("Hello")
    assert first.text == second.text == "READY"
    assert [call[1] for call in wire.calls] == ["first", "second"]
    assert first.operation_id != second.operation_id
    assert wire.closed
    with pytest.raises(RuntimeError, match="^Client is closed$"):
        client.generate("Hello")


def test_fallback_then_next_operation_returns_to_primary():
    wire = FakeTransport(
        [
            WireResponse(503, b""),
            WireResponse(200, completed("backup")),
            WireResponse(200, completed("primary")),
        ]
    )
    with FailoverClient(
        dest(), dest("backup"), policy=Policy(fallback_statuses={503}), transport=wire
    ) as client:
        assert client.generate("Hello", replay_safe=True).text == "backup"
        assert client.generate("Hello").text == "primary"
    assert [call[0] for call in wire.calls] == ["primary", "backup", "primary"]
    assert wire.calls[0][2]["input"] == wire.calls[1][2]["input"]
    assert wire.calls[0][2]["model"] != wire.calls[1][2]["model"]


@pytest.mark.parametrize(
    "status", [301, 302, 307, 400, 401, 403, 404, 408, 429, 500, 502, 503, 504]
)
def test_default_never_replays(status):
    wire = FakeTransport([WireResponse(status, b"secret-error")])
    with FailoverClient(dest(), dest("backup"), transport=wire) as client:
        with pytest.raises(FailoverError, match="^http_error$") as error:
            client.generate("private prompt", replay_safe=True)
    assert len(wire.calls) == 1
    assert "secret" not in str(error.value)
    assert "private" not in repr(error.value.attempts)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_replay_requires_caller_permission(status):
    wire = FakeTransport([WireResponse(status, b"")])
    with FailoverClient(
        dest(),
        dest("backup"),
        policy=Policy(fallback_statuses={status}),
        transport=wire,
    ) as client:
        with pytest.raises(FailoverError, match="^http_error$"):
            client.generate("Hello")
    assert len(wire.calls) == 1


def test_both_fail_exactly_two_attempts():
    wire = FakeTransport([WireResponse(503, b""), WireResponse(503, b"")])
    with FailoverClient(
        dest(), dest("backup"), policy=Policy(fallback_statuses={503}), transport=wire
    ) as client:
        with pytest.raises(FailoverError, match="^http_error$") as error:
            client.generate("Hello", replay_safe=True)
    assert len(error.value.attempts) == len(wire.calls) == 2


@pytest.mark.parametrize(
    "allow,replay,count", [(False, True, 1), (True, False, 1), (True, True, 2)]
)
def test_ambiguous_completion_requires_two_permissions(allow, replay, count):
    wire = FakeTransport(
        [TransportError("do not leak"), WireResponse(200, completed())]
    )
    with FailoverClient(
        dest(),
        dest("backup"),
        policy=Policy(allow_ambiguous_replay=allow),
        transport=wire,
    ) as client:
        if count == 2:
            assert client.generate("Hello", replay_safe=replay).text == "READY"
        else:
            with pytest.raises(
                FailoverError, match="^transport_completion_unknown$"
            ) as error:
                client.generate("Hello", replay_safe=replay)
            assert "do not leak" not in str(error.value)
    assert len(wire.calls) == count


@pytest.mark.parametrize(
    "body,reason",
    [
        (b"{}", "response_not_completed"),
        (b"not-json", "invalid_json_response"),
        (b"[]", "response_not_completed"),
        (b'{"status":"incomplete"}', "response_not_completed"),
        (b'{"status":"completed","output":[]}', "empty_text_response"),
        (b"x" * (MAX_BODY_BYTES + 1), "response_exceeds_limit"),
    ],
)
def test_unusable_success_is_not_replayed(body, reason):
    wire = FakeTransport([WireResponse(200, body)])
    with FailoverClient(
        dest(),
        dest("backup"),
        policy=Policy(fallback_statuses={503}, allow_ambiguous_replay=True),
        transport=wire,
    ) as client:
        with pytest.raises(FailoverError, match=f"^{reason}$"):
            client.generate("Hello", replay_safe=True)
    assert len(wire.calls) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://adb-100.1.azuredatabricks.net",
        "https://evil.example",
        "https://adb-100.1.azuredatabricks.net.evil.example",
        "https://user:secret@adb-100.1.azuredatabricks.net",
        "https://adb-100.1.azuredatabricks.net:443",
        "https://adb-100.1.azuredatabricks.net/?secret=a",
        "https://adb-100.1.azuredatabricks.net/#x",
    ],
)
def test_unsafe_destination_rejected(url):
    with pytest.raises(
        ValueError, match="^Expected an exact HTTPS Azure Databricks workspace URL$"
    ):
        Destination("primary", url, "demo.ai.primary", lambda: "token")


@pytest.mark.parametrize("token", ["", "a\nb", "a b", "a\x7fb", "\u00e9"])
def test_invalid_bearer_never_reaches_transport(token):
    wire = FakeTransport([])
    with FailoverClient(dest(callback=lambda: token), transport=wire) as client:
        with pytest.raises(FailoverError, match="^authentication_failed$") as error:
            client.generate("Hello")
        assert error.value.reason == "authentication_failed"
    assert not wire.calls


def test_callback_failure_is_redacted_and_not_replayed():
    def fail():
        raise RuntimeError("private token")

    wire = FakeTransport([])
    with FailoverClient(dest(callback=fail), dest("backup"), transport=wire) as client:
        with pytest.raises(FailoverError, match="^authentication_failed$") as error:
            client.generate("Hello", replay_safe=True)
    assert "private" not in str(error.value)
    assert not wire.calls


def test_deadline_includes_authentication():
    def slow():
        time.sleep(0.02)
        return "token"

    wire = FakeTransport([])
    with FailoverClient(
        dest(callback=slow), policy=Policy(total_timeout_seconds=0.001), transport=wire
    ) as client:
        with pytest.raises(FailoverError, match="^deadline_exceeded$") as error:
            client.generate("Hello")
    assert error.value.reason == "deadline_exceeded"
    assert not wire.calls


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        (
            {"fallback_statuses": {403}},
            "Only explicitly approved 429/500/502/503/504 may fall back",
        ),
        ({"total_timeout_seconds": 0}, "Timeouts must be finite positive seconds"),
        (
            {"total_timeout_seconds": float("nan")},
            "Timeouts must be finite positive seconds",
        ),
        (
            {"attempt_timeout_seconds": float("inf")},
            "Timeouts must be finite positive seconds",
        ),
    ],
)
def test_bad_policy_rejected(kwargs, reason):
    with pytest.raises(ValueError, match=f"^{reason}$"):
        Policy(**kwargs)


def test_same_destination_rejected():
    with pytest.raises(
        ValueError, match="^Destinations must have distinct names and routes$"
    ):
        FailoverClient(dest(), dest())


def test_no_backup_never_retries():
    wire = FakeTransport([WireResponse(503, b"")])
    with FailoverClient(
        dest(), policy=Policy(fallback_statuses={503}), transport=wire
    ) as client:
        with pytest.raises(FailoverError, match="^http_error$"):
            client.generate("Hello", replay_safe=True)
    assert len(wire.calls) == 1


@pytest.mark.parametrize(
    "prompt,tokens,reason",
    [
        ("", 1, "prompt must be nonempty text"),
        ("ok", 0, "max_output_tokens must be an integer from 1 to 32768"),
        ("ok", True, "max_output_tokens must be an integer from 1 to 32768"),
        ("ok", 32769, "max_output_tokens must be an integer from 1 to 32768"),
        ("x" * 1048577, 1, "Encoded request exceeds 1 MiB"),
    ],
)
def test_invalid_input_sends_nothing(prompt, tokens, reason):
    wire = FakeTransport([])
    with FailoverClient(dest(), transport=wire) as client:
        with pytest.raises(ValueError, match=f"^{reason}$"):
            client.generate(prompt, max_output_tokens=tokens)
    assert not wire.calls


def test_expired_total_budget_never_starts_backup():
    class SlowTransport(FakeTransport):
        def send(self, destination, token, payload, timeout):
            response = super().send(destination, token, payload, timeout)
            time.sleep(0.02)
            return response

    wire = SlowTransport([WireResponse(503, b"")])
    with FailoverClient(
        dest(),
        dest("backup"),
        policy=Policy(total_timeout_seconds=0.001, allow_ambiguous_replay=True),
        transport=wire,
    ) as client:
        with pytest.raises(FailoverError, match="^deadline_exceeded$") as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.reason == "deadline_exceeded"
    assert len(wire.calls) == 1
    assert wire.calls[0][3] <= 0.001


def test_tls_verification_failure_does_not_fallback(monkeypatch):
    import http.client
    import ssl

    calls = []

    class RejectTLS:
        sock = None

        def __init__(self, *args, **kwargs):
            calls.append(self)
            self.closed = False

        def connect(self):
            raise ssl.SSLCertVerificationError("secret in error")

        def close(self):
            self.closed = True

    monkeypatch.setattr(http.client, "HTTPSConnection", RejectTLS)
    with FailoverClient(
        dest(), dest("backup"), policy=Policy(allow_ambiguous_replay=True)
    ) as client:
        with pytest.raises(FailoverError, match="^tls_verification_failed$") as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.reason == "tls_verification_failed"
    assert "secret" not in str(error.value)
    assert len(calls) == 1
    assert calls[0].closed


def test_deeply_nested_json_returns_classified_error_without_replay():
    depth = 100_000
    nested = b"[" * depth + b"0" + b"]" * depth
    assert len(nested) < MAX_BODY_BYTES
    wire = FakeTransport([WireResponse(200, nested)])
    with FailoverClient(
        dest(),
        dest("backup"),
        policy=Policy(allow_ambiguous_replay=True),
        transport=wire,
    ) as client:
        with pytest.raises(FailoverError, match="^invalid_json_response$") as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.attempts[0].http_status == 200
    assert len(wire.calls) == 1
