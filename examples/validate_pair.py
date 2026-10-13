"""Preview or run a bounded validation against two preconfigured workspace routes.

The full run makes at most four live inference attempts with synthetic input.
The fallback case injects a local 503 before contacting the real backup. It is
not a Databricks fault, backend fallback test or regional disaster simulation.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from typing import Any

from inference_failover import (
    Destination,
    FailoverClient,
    FailoverError,
    HttpTransport,
    Policy,
    WireResponse,
)


def destination(prefix: str) -> Destination:
    return Destination(
        prefix.lower(),
        os.environ[f"{prefix}_WORKSPACE_URL"],
        os.environ[f"{prefix}_SERVICE"],
        lambda: os.environ[f"{prefix}_TOKEN"],
    )


class SyntheticPrimary503:
    """No primary request is sent. Only the backup uses the real transport."""

    def __init__(self) -> None:
        self.real = HttpTransport()

    def send(
        self, target: Destination, token: str, payload: bytes, timeout: float
    ) -> WireResponse:
        if target.name == "primary":
            return WireResponse(503, b"")
        return self.real.send(target, token, payload, timeout)

    def close(self) -> None:
        self.real.close()


def run_case(
    label: str, client: FailoverClient, *, synthetic_primary: bool = False
) -> dict[str, Any]:
    with client:
        try:
            result = client.generate(
                "Reply with READY.", replay_safe=synthetic_primary, max_output_tokens=64
            )
            status = "completed"
            attempts = result.attempts
        except FailoverError as error:
            status = error.reason
            attempts = error.attempts
    return {
        "case": label,
        "result": status,
        "synthetic_primary_503": synthetic_primary,
        "attempts": [
            {
                "destination": attempt.destination,
                "http_status": attempt.http_status,
                "outcome": attempt.outcome,
                "elapsed_seconds": round(attempt.elapsed_seconds, 6),
                "server_request_id": attempt.server_request_id,
                "synthetic": synthetic_primary and attempt.destination == "primary",
            }
            for attempt in attempts
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--baselines-only", action="store_true")
    parser.add_argument(
        "--receipt", help="Optional new private JSON file. Never overwritten."
    )
    args = parser.parse_args(argv)
    if not args.execute:
        print(
            json.dumps(
                {
                    "mode": "preview_no_network",
                    "maximum_live_inference_attempts": 2 if args.baselines_only else 4,
                    "max_output_tokens_per_attempt": 64,
                    "synthetic_fallback_case_included": not args.baselines_only,
                    "credentials_read": False,
                    "resources_modified": False,
                },
                indent=2,
            )
        )
        return 0
    try:
        primary, backup = destination("PRIMARY"), destination("BACKUP")
    except (KeyError, ValueError):
        print(
            "Configure valid PRIMARY/BACKUP_WORKSPACE_URL and PRIMARY/BACKUP_SERVICE."
        )
        return 2
    receipt_fd: int | None = None
    if args.receipt:
        try:
            receipt_fd = os.open(
                args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
        except OSError:
            print("Receipt path must be new and writable. No inference started.")
            return 2
    results: list[dict[str, Any]] = []
    try:
        # Each baseline has only one destination and cannot retry or fall back.
        results.append(run_case("primary_baseline", FailoverClient(primary)))
        results.append(run_case("backup_baseline", FailoverClient(backup)))
        if not args.baselines_only and all(r["result"] == "completed" for r in results):
            # The simulated primary needs no real credential. The real backup
            # retains its own callback and approved authentication boundary.
            simulated_primary = Destination(
                "primary", primary.workspace_url, primary.service, lambda: "synthetic"
            )
            results.append(
                run_case(
                    "synthetic_primary_503_to_real_backup",
                    FailoverClient(
                        simulated_primary,
                        backup,
                        policy=Policy(fallback_statuses=frozenset({503})),
                        transport=SyntheticPrimary503(),
                    ),
                    synthetic_primary=True,
                )
            )
            results.append(run_case("later_primary_baseline", FailoverClient(primary)))
        receipt = {
            "scope": "API baselines and optional synthetic client fallback only",
            "regional_disaster_recovery_validated": False,
            "cases": results,
        }
        if receipt_fd is not None:
            with os.fdopen(receipt_fd, "w", encoding="utf-8") as output:
                receipt_fd = None
                json.dump(receipt, output, indent=2)
                output.write("\n")
        print(json.dumps(receipt, indent=2))
        return 0 if all(r["result"] == "completed" for r in results) else 1
    finally:
        if receipt_fd is not None:
            os.close(receipt_fd)


if __name__ == "__main__":
    raise SystemExit(main())
