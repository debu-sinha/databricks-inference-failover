"""Preview environment configuration, or explicitly send one text operation.

Production applications should provide their approved refreshing auth callbacks.
This example rereads a supplied environment token immediately before each call.
It does not renew expired tokens. Do not place secrets in command arguments.
"""

import argparse
import os

from inference_failover import Destination, FailoverClient, FailoverError, Policy


def destination(prefix: str) -> Destination:
    return Destination(
        prefix.lower(),
        os.environ[f"{prefix}_WORKSPACE_URL"],
        os.environ[f"{prefix}_SERVICE"],
        lambda: os.environ[f"{prefix}_TOKEN"],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--replay-safe", action="store_true")
    parser.add_argument("--allow-status", action="append", type=int, default=[])
    args = parser.parse_args()
    primary, backup = destination("PRIMARY"), destination("BACKUP")
    policy = Policy(fallback_statuses=frozenset(args.allow_status))
    if not args.execute:
        print("Preview only. No tokens read, network requests or resource changes.")
        print(f"Primary route: {primary.name}, backup route: {backup.name}")
        print(f"Explicit fallback statuses: {sorted(policy.fallback_statuses)}")
        print(f"Replay declared safe: {args.replay_safe}")
        return 0
    # A synthetic prompt keeps the example independent of application data.
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
        # Print status only. An application decides where response text may go.
        print(f"Completed with {len(result.attempts)} application attempt(s)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
