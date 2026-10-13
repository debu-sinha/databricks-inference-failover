"""Preview configuration or run one text request using destination-specific M2M auth."""

import argparse
import os
from collections.abc import Callable
from typing import Protocol

from inference_failover import Destination, FailoverClient, FailoverError, Policy


class AuthConfig(Protocol):
    def authenticate(self) -> dict[str, str]: ...


def build_config(
    *, host: str, client_id: str, client_secret: str, auth_type: str
) -> AuthConfig:
    from databricks.sdk.core import Config

    return Config(
        host=host, client_id=client_id, client_secret=client_secret, auth_type=auth_type
    )


def destination(
    prefix: str, *, builder: Callable[..., AuthConfig] = build_config
) -> Destination:
    host = os.environ[f"{prefix}_WORKSPACE_URL"]
    service = os.environ[f"{prefix}_SERVICE"]
    config: AuthConfig | None = None

    def token() -> str:
        nonlocal config
        if config is None:
            config = builder(
                host=host,
                client_id=os.environ[f"{prefix}_CLIENT_ID"],
                client_secret=os.environ[f"{prefix}_CLIENT_SECRET"],
                auth_type="oauth-m2m",
            )
        authorization = config.authenticate().get("Authorization", "")
        scheme, separator, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not value:
            raise ValueError("Expected a bearer credential")
        return value

    return Destination(prefix.lower(), host, service, token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replay-safe", action="store_true")
    parser.add_argument("--allow-status", action="append", type=int, default=[])
    args = parser.parse_args()
    primary, backup = destination("PRIMARY"), destination("BACKUP")
    policy = Policy(fallback_statuses=frozenset(args.allow_status))
    if not args.execute:
        print("Preview only. No credential lookup, token acquisition or model calls.")
        print(f"Explicit fallback statuses: {sorted(policy.fallback_statuses)}")
        print(f"Replay declared safe: {args.replay_safe}")
        return 0
    with FailoverClient(primary, backup, policy=policy) as client:
        try:
            result = client.generate(
                "Reply with READY.", replay_safe=args.replay_safe, max_output_tokens=64
            )
        except FailoverError as error:
            print(f"Operation did not complete: {error.reason}")
            for attempt in error.attempts:
                print(
                    f"{attempt.destination}: {attempt.http_status}, {attempt.outcome}"
                )
            return 1
        print(f"Completed with {len(result.attempts)} application attempt(s)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
