"""Explicit fallback for stateless, nonstreaming text generation."""

from __future__ import annotations

import http.client
import json
import math
import re
import ssl
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol
from urllib.parse import urlsplit

API_PATH = "/ai-gateway/mlflow/v1/responses"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 1024 * 1024
SUPPORTED_FALLBACK_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class Destination:
    name: str
    workspace_url: str
    service: str
    token_provider: Callable[[], str] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        parts = urlsplit(self.workspace_url)
        if (
            parts.scheme != "https"
            or not re.fullmatch(
                r"adb-[0-9]+\.[0-9]+\.azuredatabricks\.net", parts.netloc
            )
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Expected an exact HTTPS Azure Databricks workspace URL")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.name):
            raise ValueError(
                "Destination name must contain 1-64 simple ASCII characters"
            )
        if not re.fullmatch(
            r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", self.service
        ):
            raise ValueError("Expected catalog.schema.service")
        if not callable(self.token_provider):
            raise ValueError("token_provider must be callable")


@dataclass(frozen=True)
class Policy:
    fallback_statuses: frozenset[int] = frozenset()
    allow_ambiguous_replay: bool = False
    total_timeout_seconds: float = 30.0
    attempt_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "fallback_statuses", frozenset(self.fallback_statuses))
        if not self.fallback_statuses <= SUPPORTED_FALLBACK_STATUSES:
            raise ValueError(
                "Only explicitly approved 429/500/502/503/504 may fall back"
            )
        for value in (self.total_timeout_seconds, self.attempt_timeout_seconds):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Timeouts must be finite positive seconds")
        if not isinstance(self.allow_ambiguous_replay, bool):
            raise ValueError("allow_ambiguous_replay must be a boolean")


@dataclass(frozen=True)
class Attempt:
    destination: str
    http_status: int | None
    outcome: str
    elapsed_seconds: float
    server_request_id: str | None = None


@dataclass(frozen=True)
class Result:
    text: str
    response: Mapping[str, Any]
    attempts: tuple[Attempt, ...]
    operation_id: str


class FailoverError(Exception):
    """Failure metadata without credentials, prompts or upstream error bodies."""

    def __init__(self, reason: str, attempts: tuple[Attempt, ...], operation_id: str):
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts
        self.operation_id = operation_id


class TransportError(Exception):
    """The request may have reached the upstream service."""


class ResponseError(Exception):
    """A response cannot be safely accepted or replayed automatically."""


@dataclass(frozen=True)
class WireResponse:
    status: int
    body: bytes
    request_id: str | None = None


class Transport(Protocol):
    def send(
        self, destination: Destination, token: str, payload: bytes, timeout: float
    ) -> WireResponse: ...

    def close(self) -> None: ...


class HttpTransport:
    """Direct HTTPS with certificate checks, no redirects and no proxy environment."""

    def send(
        self, destination: Destination, token: str, payload: bytes, timeout: float
    ) -> WireResponse:
        host = urlsplit(destination.workspace_url).netloc
        deadline = time.monotonic() + timeout
        connection = http.client.HTTPSConnection(
            host, timeout=timeout, context=ssl.create_default_context()
        )

        def remaining() -> float:
            value = deadline - time.monotonic()
            if value <= 0:
                raise TimeoutError
            return value

        def update_timeout() -> None:
            connection.timeout = remaining()
            if connection.sock is not None:
                connection.sock.settimeout(connection.timeout)

        try:
            update_timeout()
            connection.connect()
            update_timeout()
            connection.request(
                "POST",
                API_PATH,
                body=payload,
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            update_timeout()
            response = connection.getresponse()
            request_id = response.getheader(
                "x-databricks-request-id"
            ) or response.getheader("x-request-id")
            if request_id is not None and not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,128}", request_id
            ):
                request_id = None
            # Error bodies can contain prompt data. Policy needs the status only.
            if response.status != 200:
                return WireResponse(response.status, b"", request_id)
            chunks = bytearray()
            while True:
                update_timeout()
                chunk = response.read1(min(65536, MAX_BODY_BYTES + 1 - len(chunks)))
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > MAX_BODY_BYTES:
                    raise ResponseError("response_exceeds_limit")
            if response.length not in (None, 0):
                raise TransportError("truncated_response_completion_unknown")
            remaining()
            return WireResponse(response.status, bytes(chunks), request_id)
        except ssl.SSLCertVerificationError:
            raise ResponseError("tls_verification_failed") from None
        except (TimeoutError, OSError, http.client.HTTPException):
            raise TransportError("transport_completion_unknown") from None
        finally:
            connection.close()

    def close(self) -> None:
        # Every send closes its own connection, including failed requests.
        pass


def _completed_text(body: bytes) -> tuple[dict[str, Any], str]:
    if len(body) > MAX_BODY_BYTES:
        raise ResponseError("response_exceeds_limit")
    try:
        parsed = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ResponseError("invalid_json_response") from None
    if not isinstance(parsed, dict) or parsed.get("status") != "completed":
        raise ResponseError("response_not_completed")
    output = parsed.get("output")
    if not isinstance(output, list):
        raise ResponseError("unexpected_response_shape")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise ResponseError("unexpected_response_shape")
        if item.get("type") == "reasoning":
            continue
        if (
            item.get("type") != "message"
            or item.get("role") != "assistant"
            or item.get("status") != "completed"
            or not isinstance(item.get("content"), list)
        ):
            raise ResponseError("unsupported_response_item")
        for part in item["content"]:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                raise ResponseError("unsupported_response_content")
            if not isinstance(part.get("text"), str):
                raise ResponseError("unexpected_response_shape")
            texts.append(part["text"])
    text = "\n".join(texts)
    if not text.strip():
        raise ResponseError("empty_text_response")
    return parsed, text


class FailoverClient:
    """At most one request per destination. No persistent routing state."""

    def __init__(
        self,
        primary: Destination,
        backup: Destination | None = None,
        *,
        policy: Policy | None = None,
        transport: Transport | None = None,
    ) -> None:
        if backup is not None and (
            primary.name == backup.name
            or (primary.workspace_url.rstrip("/"), primary.service)
            == (backup.workspace_url.rstrip("/"), backup.service)
        ):
            raise ValueError("Destinations must have distinct names and routes")
        self._destinations = (primary,) if backup is None else (primary, backup)
        self._policy = policy or Policy()
        self._transport = transport or HttpTransport()
        self._closed = False

    def __enter__(self) -> FailoverClient:
        if self._closed:
            raise RuntimeError("Client is closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()

    def generate(
        self, prompt: str, *, replay_safe: bool = False, max_output_tokens: int = 128
    ) -> Result:
        if self._closed:
            raise RuntimeError("Client is closed")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be nonempty text")
        if not isinstance(replay_safe, bool):
            raise ValueError("replay_safe must be a boolean")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or not 1 <= max_output_tokens <= 32768
        ):
            raise ValueError("max_output_tokens must be an integer from 1 to 32768")
        operation_id = uuid.uuid4().hex
        deadline = time.monotonic() + self._policy.total_timeout_seconds
        attempts: list[Attempt] = []
        for index, destination in enumerate(self._destinations):
            payload = json.dumps(
                {
                    "model": destination.service,
                    "input": [{"role": "user", "content": prompt}],
                    "max_output_tokens": max_output_tokens,
                    "stream": False,
                }
            ).encode()
            if len(payload) > MAX_REQUEST_BYTES:
                raise ValueError("Encoded request exceeds 1 MiB")
            if time.monotonic() >= deadline:
                raise FailoverError("deadline_exceeded", tuple(attempts), operation_id)
            try:
                token = destination.token_provider()
                if (
                    not isinstance(token, str)
                    or not token
                    or not token.isascii()
                    or any(ord(c) < 33 or ord(c) > 126 for c in token)
                ):
                    raise ValueError("Invalid bearer")
            except Exception:
                raise FailoverError(
                    "authentication_failed", tuple(attempts), operation_id
                ) from None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FailoverError("deadline_exceeded", tuple(attempts), operation_id)
            start = time.monotonic()
            status: int | None = None
            server_request_id: str | None = None
            eligible = False
            try:
                response = self._transport.send(
                    destination,
                    token,
                    payload,
                    min(remaining, self._policy.attempt_timeout_seconds),
                )
                status = response.status
                server_request_id = response.request_id
                if time.monotonic() >= deadline:
                    raise TransportError("deadline_completion_unknown")
                if status == 200:
                    parsed, text = _completed_text(response.body)
                    attempts.append(
                        Attempt(
                            destination.name,
                            status,
                            "completed",
                            time.monotonic() - start,
                            server_request_id,
                        )
                    )
                    return Result(text, parsed, tuple(attempts), operation_id)
                reason = "http_error"
                eligible = status in self._policy.fallback_statuses
            except TransportError:
                reason = "transport_completion_unknown"
                eligible = self._policy.allow_ambiguous_replay
            except ResponseError as error:
                reason = str(error)
            attempts.append(
                Attempt(
                    destination.name,
                    status,
                    reason,
                    time.monotonic() - start,
                    server_request_id,
                )
            )
            if not (
                index == 0 and len(self._destinations) == 2 and replay_safe and eligible
            ):
                raise FailoverError(reason, tuple(attempts), operation_id)
        raise FailoverError("destinations_exhausted", tuple(attempts), operation_id)
