"""Actual HTTP sockets on loopback. TLS and Databricks are not tested here."""

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from inference_failover import Destination, FailoverClient, FailoverError, Policy
from inference_failover.client import API_PATH, MAX_BODY_BYTES


def body(text="READY"):
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


@pytest.fixture
def loopback(monkeypatch):
    state = {"responses": [], "requests": [], "connection_hosts": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            received = self.rfile.read(int(self.headers["Content-Length"]))
            state["requests"].append(
                (self.path, dict(self.headers), json.loads(received))
            )
            status, content, headers = state["responses"].pop(0)
            self.send_response(status)
            self.send_header("Content-Length", str(headers.pop("length", len(content))))
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def connection(host, *, timeout, context):
        state["connection_hosts"].append(host)
        assert host in {
            "adb-100.1.azuredatabricks.net",
            "adb-200.1.azuredatabricks.net",
        }
        assert context.verify_mode != 0
        return http.client.HTTPConnection(
            "127.0.0.1", server.server_port, timeout=timeout
        )

    # The production transport still sends/reads actual sockets. The test factory
    # can connect only to this loopback server, never a remote Databricks host.
    monkeypatch.setattr(http.client, "HTTPSConnection", connection)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def primary():
    return Destination(
        "primary",
        "https://adb-100.1.azuredatabricks.net",
        "demo.ai.primary",
        lambda: "primary-secret",
    )


def backup():
    return Destination(
        "backup",
        "https://adb-200.1.azuredatabricks.net",
        "demo.ai.backup",
        lambda: "backup-secret",
    )


def test_real_socket_fallback_and_later_primary_recovery(loopback):
    loopback["responses"] = [
        (503, b"sensitive upstream error", {"x-request-id": "primary-request-1"}),
        (200, body("backup"), {"x-databricks-request-id": "backup-request-1"}),
        (200, body("primary"), {}),
    ]
    with FailoverClient(
        primary(), backup(), policy=Policy(fallback_statuses={503})
    ) as client:
        first = client.generate("Hello", replay_safe=True)
        second = client.generate("Hello")
    assert first.text == "backup"
    assert second.text == "primary"
    assert len(first.attempts) == 2
    assert [a.server_request_id for a in first.attempts] == [
        "primary-request-1",
        "backup-request-1",
    ]
    assert second.attempts[0].server_request_id is None
    requests = loopback["requests"]
    assert [request[0] for request in requests] == [API_PATH] * 3
    assert [request[1]["Authorization"] for request in requests] == [
        "Bearer primary-secret",
        "Bearer backup-secret",
        "Bearer primary-secret",
    ]
    assert [request[2]["model"] for request in requests] == [
        "demo.ai.primary",
        "demo.ai.backup",
        "demo.ai.primary",
    ]
    assert all(request[2]["stream"] is False for request in requests)
    assert "sensitive" not in repr(first.attempts)


def test_unsafe_request_id_header_is_not_retained(loopback):
    loopback["responses"] = [(200, body(), {"x-request-id": "untrusted content!"})]
    with FailoverClient(primary()) as client:
        result = client.generate("Hello")
    assert result.attempts[0].server_request_id is None


def test_redirect_does_not_forward_bearer(loopback):
    loopback["responses"] = [(307, b"", {"Location": "https://evil.example/steal"})]
    with FailoverClient(primary(), backup()) as client:
        with pytest.raises(FailoverError, match="^http_error$") as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.attempts[0].http_status == 307
    assert len(loopback["requests"]) == 1
    assert loopback["connection_hosts"] == ["adb-100.1.azuredatabricks.net"]


def test_body_limit_over_real_socket(loopback):
    loopback["responses"] = [(200, b"x" * (MAX_BODY_BYTES + 1), {})]
    with FailoverClient(primary(), backup()) as client:
        with pytest.raises(FailoverError, match="^response_exceeds_limit$") as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.reason == "response_exceeds_limit"
    assert len(loopback["requests"]) == 1


def test_truncated_response_is_ambiguous_not_success(loopback):
    content = body()
    loopback["responses"] = [(200, content, {"length": len(content) + 100})]
    with FailoverClient(primary(), backup()) as client:
        with pytest.raises(
            FailoverError, match="^transport_completion_unknown$"
        ) as error:
            client.generate("Hello", replay_safe=True)
    assert error.value.reason == "transport_completion_unknown"
    assert len(loopback["requests"]) == 1


def test_same_status_429_requires_explicit_policy(loopback):
    loopback["responses"] = [(429, b"admission limit", {})]
    with FailoverClient(primary(), backup()) as client:
        with pytest.raises(FailoverError, match="^http_error$"):
            client.generate("Hello", replay_safe=True)
    assert len(loopback["requests"]) == 1
