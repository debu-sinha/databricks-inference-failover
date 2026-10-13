# Validate your deployment

This is a test plan, not a record of passed tests or permission to change a deployment. The [validation record](validation.md) lists completed checks and their limits. Local behavior, live inference and regional disaster recovery require different evidence.

## Agree the test contract first

Record the following in the deployment's private acceptance record before execution. Resolve missing values with the application, identity and service owners. Do not fill them with assumptions.

| Decision | Required value |
| --- | --- |
| Application scope | Text-only nonstreaming input, output contract, user authorization and any downstream actions |
| Model and API | Exact model/version, serving mode, API path and request options on each route |
| Destinations | Workspace URLs, model services, cloud, metastores, allowed processing locations and capacity |
| Identity | Principal, issuer, method, effective grants, renewal and rotation owner for each route |
| Failure policy | Allowed HTTP statuses, replay policy, duplicate-work handling and combined retry budget |
| Recovery objective | Maximum accepted interruption, restoration owner, healthy observation period and return-to-primary policy |
| Load | Input/output sizes, arrival rate, concurrency, duration, latency/error thresholds and backup headroom |
| Test authority | Owner, isolated environment, permitted actions, call/token/cost budget, window, stop conditions and rollback |

Use synthetic inputs until data handling is approved. Permission for more inference calls does not authorize resource changes, fault injection, service-principal creation or a load test. Preserve unused budget for verification after a failed test or rollback.

Each test result needs a status: `not run`, `passed`, `failed`, `blocked` or `outside agreed scope`. Name the unmet prerequisite for a blocked case. Only the accepting owner can exclude a requirement. A planned test is never a passed result.

## A. Library and published examples

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| A1 | Clean environment, final candidate commit and pinned dependencies. Run installation, full suite, lint, format and type checks. | Exact commands, versions and exit results match the candidate being reviewed |
| A2 | Exercise the public library API with controlled primary, backup and failure responses. | Default stops after primary. Explicit replay approval plus allowed status permits at most one backup attempt. Exhaustion stops. A new operation starts at primary |
| A3 | Exercise invalid routes, tokens, input and output, redirects, TLS errors and bounded response handling. | Invalid input is rejected, credentials stay on their configured host and no denied case silently falls back |
| A4 | Run the installed offline demo and every published example in preview mode, including invalid flags and configuration. | Previews perform no credential lookup or network calls. Errors produce useful, secret-free diagnostics |
| A5 | With approved routes, identity and budget, execute the published entry points used by the deployment. | Record which of `application.py`, `application_oauth.py` and `validate_pair.py` ran. A private runner does not prove an unexecuted public entry point |
| A6 | After both live baselines pass, run the full pair-validator sequence if budget permits. | Its locally injected 503 is labeled synthetic. Real backup completion proves the client branch. The later primary baseline is not reported as outage recovery |

Use [setup](setup.md) for commands. A successful user-identity call validates that identity and route. It does not validate service-principal M2M.

## B. Production identity and application authorization

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| B1 | Approved Databricks-managed service principal, OAuth secret and grants in each intended workspace. Run the M2M example separately against primary and backup. | The intended service principal completes inference on each route with its own configured host and credential context |
| B2 | Approved window spanning actual token expiry. Reuse the application's credential contexts in one process and call both destinations before and after renewal. | Fresh token acquisition is observed without recording token values. Later inference succeeds on both routes. Restarting the process, changing the clock or using a user token does not pass this case |
| B3 | Isolated denied or invalid credentials and an approved negative-test plan. | Token acquisition failure, HTTP 401 and HTTP 403 stop. No backup call or privilege substitution occurs |
| B4 | A dedicated test secret, rotation owner and rollback. Test rotation and revocation without touching shared production credentials. | New credentials work. The revoked or expired credential fails as expected. Secret distribution and rollback work without exposing values |
| B5 | The actual application user-authentication and authorization layer. Test allowed, denied and cross-tenant requests. | Access is enforced before inference. A supplied user-ID header cannot grant access or select a privileged destination |

The [M2M documentation](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/oauth-m2m) describes token renewal. [Model-service governance](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-services#governance-and-privileges) describes caller and owner permissions. Documentation and mocked callbacks are prerequisites, not live identity results.

## C. Real upstream failure and restoration

This stage needs an isolated, owner-approved setup. No existing fault endpoint is assumed. The current pair validator injects its 503 locally and cannot pass the real-upstream cases below.

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| C1 | A documented, reversible way to cause a real eligible failure in an isolated upstream. Run through the final application client. | Actual primary service failure, client classification and real backup completion are correlated with service evidence and request IDs |
| C2 | Separate approved 429 and 503 cases, with the source of the 429 established. | Default policy stops. Only the specifically enabled status falls back when replay is approved. A 429 route does not bypass an intended quota, budget or admission control |
| C3 | Approved invalid-request, missing-service and access-denied cases. | HTTP 400, 401, 403 and 404 do not trigger backup. Diagnostics do not expose credentials or upstream content |
| C4 | Controlled failures on both test routes. | One classified final failure, bounded attempt counts and no retry loop. The application returns its agreed error response |
| C5 | Restore the genuinely failed upstream and observe it for the agreed period. | Primary inference succeeds after restoration. Record actual interruption and recovery times. A healthy call after a synthetic error does not pass |
| C6 | Read the actual Gateway and application retry configuration. Observe a permitted fallback case. | Application attempts and Gateway destination attempts remain within the accepted latency, request and cost budgets |

Review [Gateway routing](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/configure-traffic-splitting), [usage records](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/usage-tracking) and the relevant [Foundation Model API limits](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/limits). A quota error and an availability error need different operational decisions. Neither alone proves a regional outage.

### Prepare the isolated fault change for review

The proposed change record must identify the service and owner, exact fault mechanism, expected status, isolation boundary, start/stop commands, maximum duration and restoration steps. Attach a configuration snapshot and an independently executable rollback. Do not run it until the owner accepts the exact change.

1. Confirm that the chosen model service and upstream are dedicated to the test. Shared pay-per-token capacity is not a resource this package can stop or manipulate.
2. Establish healthy primary and backup baselines and capture request IDs.
3. Apply only the approved isolated fault. Confirm its observed status before enabling the matching fallback policy. If the status differs, stop and review it.
4. Make one synthetic, replay-safe operation. Correlate the primary failure and backup completion. Keep a both-failing case separate so it has its own approved mechanism and budget.
5. Restore the exact original configuration, verify readback, then prove successful inference and the agreed healthy observation period.
6. Stop on unexpected shared impact, incorrect identity or target, exhausted budget, excessive retries or failed restoration. Keep the incident owner engaged until restoration is verified.

A test upstream that intentionally returns an error can validate the routing path through that upstream. It cannot attest failure of managed model capacity or a whole region. If the actual serving mode has no approved fault mechanism, keep C1 and C5 blocked and request a supported test method from its owner.

## D. Ambiguous completion and time budgets

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| D1 | Controlled connection loss after request acceptance with a side-effect-free synthetic request. | Default reports completion unknown and does not replay. Explicit ambiguous replay records that duplicate inference may have occurred |
| D2 | Any application action triggered by model output has an agreed deduplication or transaction design. Test duplicate completion and worker restart. | No duplicate business action occurs within that design's stated scope. This library provides no exactly-once guarantee |
| D3 | Controlled delays in credential acquisition, DNS, connection/TLS, status/headers and body reads. | Measure wall-clock time, attempt count, worker lifetime and cleanup. Report delays beyond cooperative budgets instead of treating configured timeouts as hard deadlines |
| D4 | If the application requires a strict deadline, test its supervisor or isolation mechanism. | User-visible latency and local resource cleanup meet the agreed bound. Stopping local work is not claimed to cancel already admitted inference |

Do not test ambiguous replay with business side effects until D2 is accepted. See [production integration](production.md) for the pinned SDK and synchronous callback limits. Streaming, tool execution, background operations and prior-response continuation remain outside this library's supported interface.

## E. Load, placement and complete DR

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| E1 | Accepted load shape, isolated targets, monitoring and cost ceiling. Increase only to the agreed concurrency and duration. | Completed throughput, p95/p99 latency, error rate, fallback rate, concurrent work and cost meet thresholds at agreed input/output sizes |
| E2 | Accepted failure-load scenario and independently confirmed backup capacity. | Backup sustains the required admitted load without uncontrolled retry multiplication, queue growth or loss of application authorization |
| E3 | Authoritative deployment evidence for the exact model and serving mode. | Approved physical processing placement, independent capacity and shared failure dependencies are established. Two workspace URLs or two HTTP 200 responses are insufficient |
| E4 | Reviewed entry-point and dependency outage plan with rollback. | The actual application remains usable, or recovers within its accepted objective, when the selected ingress, workspace entry point, network, identity issuer or secret-store dependency is unavailable |

Map the application's hosting, DNS, ingress, identity, secrets and observability dependencies before E4. Workspace location alone is not inference-location evidence. Review the applicable [processing-location documentation](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/compliance). A locally returned 503 does not establish regional DR.

## F. Shared gateway integration

These cases apply when several applications need one API address with routing managed centrally. No shared gateway, APIM policy or shared Python service has been deployed or tested by this repository. Existing client tests and live calls do not pass these cases. Evaluate an existing gateway before adding another service. See [ADR 002](adr-002.md).

| ID | Prerequisite and test | Pass evidence |
| --- | --- | --- |
| F1 | An agreed inbound API contract and exact backend model mapping. Send the real application request through the chosen shared layer to each route independently. | Request fields, response shape, model/version, error mapping and supported options match the application contract. Unsupported streaming or tool requests are rejected clearly rather than silently altered |
| F2 | The shared layer's actual caller authentication, tenant policy and Databricks credential integration. Test allowed and denied callers, forbidden models, each backend identity and token renewal. | Unauthorized calls stop before inference. Route credentials remain bound to the intended host. The backup does not widen the caller's allowed data locations, model access or privileges |
| F3 | The deployed gateway's documented retry, circuit-breaker and recovery policy. Exercise the approved primary failure, both routes failing and primary restoration. | Measured attempt count, errors, latency, backup use and recovery match that policy. A per-request retry is not reported as persistent traffic switching, and one instance's state is not assumed to represent every instance |
| F4 | An approved outage of the primary workspace entrypoint, with independent gateway availability and network monitoring. | Applications continue through the same agreed API address within the recovery objective. Actual destination use is established. A synthetic model error does not pass this workspace-entrypoint case |
| F5 | An approved gateway-instance or gateway-region outage test, including DNS, ingress, identity, secrets and networking. | The shared entrypoint remains available or recovers within the accepted objective. Backend redundancy alone is not accepted as gateway availability |
| F6 | Representative multi-application load with tenant admission controls and backup capacity. | The admitted load, cost, error rate and latency meet agreed thresholds without retry multiplication or cross-tenant access. Healthy traffic is measured after restoration |

For an existing API gateway, retain its exact tier, deployment mode, policies and backend authentication configuration with the results. For a custom Python service, also test its HTTP server, bounded concurrency, cancellation, health checks, deployment and rollback. These controls are not supplied by importing this library. Do not assume an Azure identity token is the Databricks credential accepted by either route. Verify the selected authentication integration explicitly.

Keep model-backend failure, workspace-entrypoint failure and shared-gateway failure as separate acceptance cases. Confirm effective routing and access configuration before each authorized test. A rate-limit response by itself is not evidence of a regional outage.

## Record results and accept the scope

For each case retain its ID, status, owner, date, command, package commit, runtime version, sanitized configuration, timestamps, attempt metadata and applicable server request IDs. Keep exact topology, identities and traces in approved private storage. Do not commit credentials, prompts, customer outputs, internal tickets or work screenshots.

Have a reviewer compare the final code, examples, diagrams and claims with those results. Open material requirements prevent production acceptance. They do not erase narrower successful results. Record the accepted deployment scope, remaining exclusions, operational owner and rollback before release.
