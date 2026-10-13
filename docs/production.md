# Prepare the shared routing deployment

This repository contains a reference client and an acceptance plan. The target deployment gives applications one API and manages routing centrally to the same approved model/version. Installing the package does not deliver that endpoint or approve production use.

## Select the routing owner first

Evaluate the existing gateway before adding a Python service. For APIM, prepare backend configuration, route-specific authentication, model and request mapping, replay policy and operational tests. Its backend pools and circuit breakers are documented capabilities. This repository contains no tested APIM policies or deployment. Python from the package cannot be placed inside an APIM policy. [APIM backends](https://learn.microsoft.com/en-us/azure/api-management/backends).

Keep a route worksheet with each workspace, regional metastore, service, approved model/version, capacity and runtime identity. For PT, prepare a region-local model service and PT endpoint in each regional metastore, with cross-workspace routing outside those services. For PPT, obtain evidence of processing locations and capacity independence rather than inferring them from workspace URLs.

Decide which layer owns retries and which owns persistent health state. APIM uses lower-priority backends only when all higher-priority backends are unavailable because their circuit breakers are tripped. That differs from this client's immediate, per-request backup decision. Define behavior for the first failed request, subsequent requests, both routes failing and restoration before deployment. [Backend priority routing](https://learn.microsoft.com/en-us/azure/api-management/backends#load-balanced-pool).

## If the selected design needs the client

Import `FailoverClient` into the shared Python API service or worker. Individual applications can also use it, but that is an alternative to the single shared routing requirement. Keep caller authentication and tenant/data authorization ahead of inference. Put destination settings under deployment control, not user control. The client is synchronous. Run it in a bounded worker when the service uses an async handler. A cancelled waiting task does not prove the worker or upstream request stopped.

The library has no persistent health state. Each operation starts at primary and may try backup once. It does not switch all traffic, replicate data or decide when an outage has ended. The shared service must define its API error for `FailoverError`, admission controls and deployment behavior. If it needs circuit breaking or controlled failback, design those mechanisms and their concurrency tests separately.

## Use renewable credentials

The following applies to the Python OAuth example. An APIM integration needs its own reviewed credential-acquisition and renewal setup. The example does not configure APIM authentication.

The [OAuth example](../examples/application_oauth.py) uses a separate SDK `Config` for each destination, with explicit host, client ID, client secret and `auth_type='oauth-m2m'`. Each callback calls `Config.authenticate()` and extracts its bearer header. SDK 0.110.0's M2M provider uses a refreshable token source. [SDK authentication](https://databricks-sdk-py.readthedocs.io/en/latest/authentication.html), [SDK source](https://github.com/databricks/databricks-sdk-py).

Keep each configuration object for its credential context rather than constructing it on every model call. Do not cache the returned bearer string forever. Inject secrets from the deployment's secret manager. Restrict access to the runtime identity, rotate through the normal process and keep debug credential logging disabled.

The OAuth example has offline tests for destination mapping and deferred acquisition. Those tests do not validate live M2M issuance, renewal or revocation. A live run with a person's OAuth profile is not a test of service-principal M2M authentication.

In SDK 0.110.0, the inspected OAuth `retrieve_token` implementation makes its token request without an explicit request timeout. Do not assume the inference client's deadline or SDK `http_timeout_seconds` bounds token acquisition. Review the pinned auth implementation, then provide bounded acquisition or supervised workers before accepting a strict request deadline. [Versioned OAuth source](https://github.com/databricks/databricks-sdk-py/blob/v0.110.0/databricks/sdk/oauth.py).

## Choose failure policy before enabling it

Set statuses from the failure cases the application can tolerate. Default fallback is disabled. `replay_safe=True` means the caller has approved replay of this operation. It is not an idempotency key. Transport failure can leave the first completion unknown and requires a separate opt-in. This version excludes streaming and tools to keep replay decisions explicit.

Review any Gateway-managed fallback with this client policy. One application attempt may include multiple destination attempts inside Gateway. Set a combined cost and latency budget. The current library does not retry the same destination or implement backoff, admission control or concurrency limits. Provide those controls in the application and test them under expected load.

Time budgets are cooperative. Token callbacks, DNS resolution, slowly arriving HTTP status and headers, and repeated low-level reads can return later than a nominal budget. If a strict wall-clock bound is required, isolate work behind a supervisor and test cancellation and resource cleanup. Terminating local work still does not cancel an upstream inference already admitted.

## Deploy and accept in stages

1. Select and review the shared routing integration. If it uses the Python client, pin and package the reviewed version. Install the `auth` extra only if using the M2M example.
2. Confirm both destinations, the same approved model/version, grants, approved processing locations and capacity with the administrators. Document model alias changes and prevent silent substitution.
3. Validate production-style identity in nonproduction, including issuance, expiry, renewal, revocation and rotation.
4. Test primary and backup independently through the shared API. Then test approved failure and recovery cases, including both routes failing, using synthetic inputs. Verify caller authorization and error responses too.
5. Run representative load against an approved test environment. Measure success rate, p95/p99 latency, fallback rate, concurrent requests and cost. Agree thresholds before the run.
6. Release to a bounded portion of traffic with an owner monitoring results. Keep a deployment rollback and a way to disable fallback. Define the restoration checks before returning traffic to primary. A client rollback does not restore data or undo upstream requests.

Shared gateway hosting, ingress, identity and secret stores can be shared failure points. A Databricks App is an optional host for a custom backend, not a tested deployment in this repository. APIM regional gateway availability is separate from backend fallback and depends on the selected tier and network setup. [APIM multi-region deployment](https://learn.microsoft.com/en-us/azure/api-management/api-management-howto-deploy-multi-region).

Two workspace URLs do not establish independent inference regions. A complete DR decision needs actual topology and processing-location evidence. See [architecture](architecture.md).

## Operational signals

Record operation ID, safe destination label, status, elapsed time and outcome. `Attempt.server_request_id` retains a safe request ID from a recognized response header when present. It can be absent, including when a transport or response-parsing failure prevents a complete transport result. The client operation ID stays local and is not a Gateway invocation ID or an upstream idempotency key. Use available server IDs with authorized Gateway records when investigating. Alert on exhausted attempts, authentication failures, rising backup traffic and latency against agreed thresholds. Keep outputs, prompts, tokens and upstream error bodies out of routine logs. Protect logs with the application's access and retention policy.

Link the deployment's incident procedure to the approved recovery steps and owners. Specify who can change routing, who checks data policy, how to disable fallback and how to verify primary recovery. Use the [acceptance checklist](acceptance.md) and retain the actual commands, versions and results in the deployment's private test record.

Public documentation and SDK 0.110.0 source checked October 13, 2026. See [validation](validation.md) for execution evidence and remaining checks.
