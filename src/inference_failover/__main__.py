"""Run an offline policy demonstration. This command never opens a socket."""

import json

from .client import Destination, FailoverClient, Policy, WireResponse


class DemoTransport:
    def send(
        self, destination: Destination, token: str, payload: bytes, timeout: float
    ) -> WireResponse:
        if destination.name == "primary":
            return WireResponse(503, b"")
        body = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "Offline backup reply"}
                    ],
                }
            ],
        }
        return WireResponse(200, json.dumps(body).encode())

    def close(self) -> None:
        pass


def main() -> None:
    primary = Destination(
        "primary",
        "https://adb-100000000.1.azuredatabricks.net",
        "demo.ai.primary",
        lambda: "offline",
    )
    backup = Destination(
        "backup",
        "https://adb-200000000.2.azuredatabricks.net",
        "demo.ai.backup",
        lambda: "offline",
    )
    with FailoverClient(
        primary,
        backup,
        policy=Policy(fallback_statuses=frozenset({503})),
        transport=DemoTransport(),
    ) as client:
        result = client.generate("Synthetic demo", replay_safe=True)
    print("Offline demonstration. No network or model calls.")
    for attempt in result.attempts:
        print(f"{attempt.destination}: HTTP {attempt.http_status}, {attempt.outcome}")
    print(result.text)


if __name__ == "__main__":
    main()
