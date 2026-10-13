# Validation record

Date: October 13, 2026.

Production acceptance is blocked. The local checks passed, but the extended live run stopped when one of four concurrent requests returned HTTP 200 and failed the client's completed-response check. Across all runs so far, 22 remote API requests produced 19 completed responses, two expected 401/404 rejections and one `response_not_completed` result. The cause of that last result is not established.

## Environment and local checks

The final local pass used a clean virtual environment with the package installed using `.[dev,auth]`. Versions were Python 3.12.10, pytest 8.4.2, Ruff 0.15.17, mypy 1.19.1 and Databricks SDK 0.110.0. The build backend is pinned to setuptools 80.9.0. The configured CI matrix includes other Python versions, but this record does not claim those jobs have run.

Run these commands from the repository root with that environment active:

```bash
python -m pip install -e '.[dev,auth]'
python -m ruff check .
python -m ruff format --check .
python -m mypy
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m inference_failover
python examples/validate_pair.py --baselines-only
```

| Check | Final result | Coverage |
| --- | --- | --- |
| Tests | 75 passed in 3.36 seconds | Policy, validation, authentication callback behavior, failure classification, bounded attempt counts, receipts and examples |
| Local HTTP integration | Passed within the test suite | Actual loopback sockets through the client transport, including fallback, later primary reuse, separate credentials, redirect rejection, truncated and oversized bodies, and request-ID capture |
| Ruff lint | Passed | Published Python files |
| Ruff formatting | Passed, 10 files | Published Python files |
| Strict mypy | Passed, six source files | Library and examples |
| Installed package and offline example | Passed | Import and an offline primary-503/backup-200 sequence |
| Pair-validation preview | Passed | No configuration or token resolution, no network calls |
| Independent code review | Passed for reference scope, including the final result record | The concurrency result remains under investigation. This is not production approval |

The loopback server tests substitute a local connection for the remote TLS connection. They do not establish real certificate negotiation, Databricks behavior, processing location or capacity. A separate unit test verifies that a certificate-verification exception stops without fallback. Tests of auth callbacks do not prove live token renewal.

## Real-data verification

The live checks used existing authorized Azure workspace routes, the model service `system.ai.gpt-oss-20b`, and `/ai-gateway/mlflow/v1/responses`. Requests were synthetic, nonstreaming text operations with at most 64 requested output tokens each. No resource configuration was changed.

The first four live calls exercised the library through a private test runner. The first call began at 19:27:19 UTC. The next two calls exercised the public pair-validation example after request-ID capture was added. Those initial six real calls returned HTTP 200 and completed responses. The separate synthetic 503 was generated locally and made no primary service request.

| Case | Real inference calls | Observed result | What it establishes |
| --- | --- | --- | --- |
| Primary baseline through the library | 1 | HTTP 200, completed | The selected primary route accepted this request |
| Backup baseline through the library | 1 | HTTP 200, completed | The selected backup route accepted this request |
| Synthetic primary 503 to real backup | 1 | Locally injected 503, then real backup HTTP 200 | The explicit application fallback branch reached the real backup successfully |
| Later primary baseline | 1 | HTTP 200, completed | A later operation could use primary again. Primary had not suffered a real outage |
| Final primary baseline through the public example | 1 | HTTP 200, completed, server request ID captured | The final example and metadata path worked on this selected primary route |
| Final backup baseline through the public example | 1 | HTTP 200, completed, server request ID captured | The final example and metadata path worked on this selected backup route |

That two-call run used this command with approved environment configuration and credentials already provided:

```bash
python examples/validate_pair.py --execute --baselines-only --receipt <new-private-json-file>
```

Redacted output subset from that exact run. Server request IDs are omitted. All remaining values below match the private receipt:

```json
{
  "regional_disaster_recovery_validated": false,
  "cases": [
    {
      "case": "primary_baseline",
      "result": "completed",
      "synthetic_primary_503": false,
      "attempts": [
        {
          "destination": "primary",
          "http_status": 200,
          "outcome": "completed",
          "elapsed_seconds": 2.012578,
          "synthetic": false
        }
      ]
    },
    {
      "case": "backup_baseline",
      "result": "completed",
      "synthetic_primary_503": false,
      "attempts": [
        {
          "destination": "backup",
          "http_status": 200,
          "outcome": "completed",
          "elapsed_seconds": 1.33392,
          "synthetic": false
        }
      ]
    }
  ]
}
```

The receipt path must be new and writable. The example creates it with mode 0600 and refuses an existing path before inference. The public example's receipt contains sanitized status and attempt metadata, not tokens, prompts, response text or model-service names. Exact target identities, timestamps and request identifiers remain in the private test record.

## Extended live run, 19:47 UTC

A separately authorized extended run started at 19:47:25 UTC and stopped at 19:47:45 UTC. It made 12 remote API requests. It used the same two existing routes and verified user identity. It changed no resources or limits, performed no same-destination retries and requested at most 64 output tokens per call.

The checked client source SHA256 was `5bb7090b2ecb63aefa5c731d2c1a9df50cccd6ce3a9906633edbb843c45acf7e`.

| Case | Remote API requests | Result |
| --- | --- | --- |
| Published application example, primary route | 1 | Completed, exit code 0 |
| Published application example, backup configured as primary | 1 | Completed, exit code 0 |
| Published full pair validator | 4 | Both baselines, synthetic-primary-503 to real backup, and later primary call completed |
| Invalid bearer | 1 | Expected HTTP 401, one attempt, no fallback |
| Nonexistent model service | 1 | Expected HTTP 404, one attempt, no fallback |
| First concurrency wave, at most four simultaneous requests | 4 | Three completed. One primary request returned HTTP 200 with `response_not_completed` |
| Planned second concurrency wave | 0 | Not run after the first wave failed |

The published entry points were exercised with these commands. Environment values and the new private receipt path are omitted:

```bash
python examples/application.py --execute
python examples/validate_pair.py --execute --receipt <new-private-json-file>
```

The application command ran twice, with the two configured routes swapped for the second run. The full validator's 503 was injected locally. It made no primary HTTP request for that injected failure. The actual backup request completed, so the published full example now has live coverage of that application branch. It still does not establish a real upstream outage or native Gateway fallback.

Exact redacted subset for the unexpected concurrency result. The server request ID is omitted:

```json
{
  "case": "concurrency_wave_1_3",
  "outcome": "response_not_completed",
  "attempts": [
    {
      "destination": "primary",
      "http_status": 200,
      "outcome": "response_not_completed",
      "elapsed_seconds": 3.7283314999658614
    }
  ],
  "expected_status": 200,
  "matched_expectation": false
}
```

The runner exited with `concurrency_smoke_failure` after that wave. The raw response body and its response-status fields were not retained for this request. The receipt does not establish whether the cause was an incomplete model response, an unexpected response shape or another condition. It does not establish a client defect or an upstream defect. Do not label the concurrency check passed or infer throughput acceptance from the other three completions.

Cumulative accounting, including the diagnostic pass below, is 22 remote API requests: 19 completed, two expected HTTP rejections and one HTTP 200 rejected by the completed-response check. The two locally injected 503 responses, one in each synthetic-fallback run, are excluded from remote request counts.

### Diagnostic follow-up

Four diagnostic calls started at 19:49:51 UTC using the unchanged client source SHA256 recorded above. Each requested at most 64 output tokens. The observer retained safe response-status and shape metadata without prompt or output text. All four calls completed with HTTP 200 and response status `completed`.

| Diagnostic call | Route | HTTP status | Response status | Reported output tokens |
| --- | --- | --- | --- | --- |
| 1 | Primary | 200 | completed | 27 |
| 2 | Backup | 200 | completed | 25 |
| 3 | Primary | 200 | completed | 20 |
| 4 | Backup | 200 | completed | 28 |

These later completions did not reproduce or explain the earlier `response_not_completed` result. They do not establish its cause, resolve the failed concurrency check or prove recovery from an upstream outage. The original failed result remains open.

The original six-call allowance was used. The later 20-request allowance has used 16 requests: 12 in the extended run and four diagnostics. Four remain unused. Further calls must remain within the current explicit test scope and budget. Commands using `--execute` can incur inference charges.

## Work remaining before production acceptance

- Read and reconcile the latest applicable Engineering confirmation with the intended model, serving mode, API and deployment topology.
- Validate the customer's required model and version on both approved destinations. The GPT OSS 20B smoke result does not validate another model.
- Run the OAuth M2M example against approved service principals and both target workspaces. Verify permissions, token expiry, refresh and authentication failure handling. Local tests and the existing user-authenticated calls do not establish that example's live authentication behavior.
- Exercise a real, approved upstream failure through the final client and public validation example. The synthetic 503 did not disable primary, emulate a Databricks outage or test native Gateway fallback.
- Restore the failed upstream and prove successful primary reuse under the agreed recovery policy. A later healthy baseline after a synthetic error is not a recovery test.
- Establish permitted processing locations, same-model compatibility and independent backup capacity. Two workspace URLs and two successful responses do not prove separate physical serving regions.
- Validate loss of the workspace entry point, network and identity dependencies when regional DR is required. Application fallback between reachable services does not cover those failures by itself.
- Resolve and reproduce the failed concurrency check before testing the agreed request sizes, concurrency, throughput, latency, error rate and recovery objective. These bounded checks cannot establish production load acceptance.
- Review total retry multiplication across the application, client and Gateway. The client does not provide exactly-once execution. A timeout or connection loss can leave upstream completion unknown.
- Confirm that the application's needs fit the supported text-only, nonstreaming interface. Streaming, tools, prior-response continuation and background operations are outside this version.
- Account for cooperative time budgets. DNS, credential callbacks and a slowly delivered HTTP header are not forcibly cancelled at a hard wall-clock deadline. A separately enforced deadline is needed where that guarantee is required.

Earlier experiments with other scripts do not close these checks. See the [acceptance matrix](acceptance.md) for deployment acceptance criteria. The package remains a reference implementation until the applicable live checks and owner acceptance are complete.
