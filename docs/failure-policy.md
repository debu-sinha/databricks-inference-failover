# Choose when to use backup

The default policy makes one primary request and stops if it fails. To enable backup, choose the allowed HTTP statuses and set `replay_safe=True` for requests your application can safely repeat.

```python
policy = Policy(
    fallback_statuses=frozenset({502, 503, 504}),
    allow_ambiguous_replay=False,
    attempt_timeout_seconds=10,
    total_timeout_seconds=30,
)
```

These values are an example, not a measured service target. Use your application's latency budget and an agreed failure policy.

| Primary result | Default behavior | How to permit backup |
| --- | --- | --- |
| HTTP 200 with completed supported text | Return the result | Backup is not needed |
| HTTP 500, 502, 503 or 504 | Stop | Add the exact status to `fallback_statuses` and declare replay safe |
| HTTP 429 | Stop | Add 429 only after confirming fallback is allowed by the admission, spend and capacity policy |
| HTTP 400, 401, 403 or 404 | Stop | Not supported as a fallback trigger. Fix input, credentials, grants or configuration |
| Other HTTP status, including redirects | Stop | Not supported as a fallback trigger |
| Timeout or connection loss | Stop with completion unknown | Both `allow_ambiguous_replay=True` and `replay_safe=True` are required |
| Invalid TLS certificate | Stop | No fallback. Investigate the trust/configuration failure |
| Token callback fails | Stop | No fallback. Fix authentication |
| HTTP 200 with malformed, incomplete, oversized or unsupported content | Stop | No automatic fallback |
| No operation time remaining | Stop | No second request |
| Backup also fails | Raise `FailoverError` | No third destination or same-destination retry |

`replay_safe` is an assertion by the application. The library cannot decide whether the business operation is safe to repeat. Model inference can already have run when the response is lost. A repeat can create another charge and a different answer. This version does not execute tools or other external side effects.

## Keep one retry owner

There is no same-destination retry or retry loop. Only one backup attempt can occur. No backoff wait or `Retry-After` scheduling is implemented because this client does not retry the same destination. Your application still needs admission control so an outage does not move more traffic to backup than it can handle.

Inspect the Gateway service's own fallback policy too. One application request can include multiple Gateway destination attempts. Do not infer total backend traffic from this library's two-attempt ceiling. [Gateway fallback behavior](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/configure-traffic-splitting).

## Recovery and time limits

Every new operation starts at primary. The library does not remember failures, open a circuit or wait for a health probe. This makes the behavior easy to inspect, but primary outages can add latency to every request. Add a reviewed circuit breaker or operator-controlled route change if your production requirements need it. Test its concurrency and recovery behavior before enabling it.

Time limits are cooperative. The client checks remaining time around attempts and body reads and configures socket timeouts. A blocking token callback, DNS resolution or slowly arriving status/headers can exceed the nominal budget. These values are not a hard wall-clock deadline. A hard bound requires a separately bounded runtime or transport. Stopping a local worker also does not prove upstream inference stopped.

Never classify a successful later primary request as recovery from a regional outage unless a real, approved outage and restoration were part of the test.
