# Where the client fits

This is a proposed application integration, not a validated regional deployment. Install the `inference_failover` library in the backend that already handles application requests. It makes outbound HTTPS inference calls. It does not run inside Unity Gateway, and it does not require a notebook or an attached cluster.

![Application-owned fallback and identity boundaries](architecture.png)

## Request flow

1. The user signs into your application. Your backend verifies the session and decides whether that user can use this feature and access the data in the prompt.
2. The backend calls `FailoverClient.generate`. Configuration supplies the exact primary and backup workspace URLs, model-service names and separate token callbacks.
3. The client obtains the primary credential and makes one nonstreaming request to the primary route.
4. A backup request happens only when the caller sets `replay_safe=True` and the failure matches the explicitly configured policy. Default policy allows no fallback. Transport errors also require `allow_ambiguous_replay=True` because the first request might have completed upstream.
5. The caller receives a completed text result and attempt metadata, or a `FailoverError`. Every new operation starts at primary. There is no persistent circuit breaker, automatic health probe or scheduled failback in this version.

The library posts to `/ai-gateway/mlflow/v1/responses` with a fully qualified model-service name. This is the documented unified Unity Gateway interface. It is different from legacy Model Serving endpoint paths. [Query model services](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/query-model-services).

## Who owns each part

| Part | Responsibility |
| --- | --- |
| Application backend | User authentication, tenant and data authorization, request admission, whether replay is safe, and handling the returned result |
| This library | At most one application-owned attempt per destination, explicit fallback policy, bounded response parsing and attempt metadata |
| Token provider | Acquire and refresh credentials for its configured destination, protect secrets, and impose its own timeout |
| Databricks administrators | Workspace access, service grants, model-service configuration and approved data-processing policy |
| Deployment and operations team | Application availability, DNS and networking, capacity, alerting, recovery tests and release acceptance |

A web service or worker can host this library. Containers, virtual machines or a managed application platform are deployment choices, not dependencies of the reference client. Choosing Databricks Apps or any other host does not by itself establish regional survivability. The application host, identity service, secret store and network all belong in the recovery design.

## Two fallback layers

Unity Gateway can perform its own ordered destination fallback within a model service. The application may then make a separate call to the configured backup workspace URL. Review both policies together because one application attempt can contain several Gateway attempts. [Gateway routing and fallbacks](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/configure-traffic-splitting).

This library does not modify Gateway configuration or move model capacity. A backup route must already work with the intended identity, model, input shape and load. Prefer the same validated model contract on both routes. Any model change needs an application-quality review.

## What this does not prove

Two workspace URLs do not prove two independent inference regions. Foundation Model API processing depends on the workspace and model and can occur outside the workspace region within the relevant Geo. Confirm the actual failure domains and approved processing locations before describing this as regional DR. [Data processing and residency](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/compliance#data-processing-and-residency).

This version supports text-only, stateless, nonstreaming generation. It does not execute tools, resume streams, migrate conversation state, replicate application data or reserve backup capacity. A timeout can leave completion unknown. Replay can produce duplicate work or charges. Time budgets are cooperative, not hard wall-clock guarantees. The synchronous token callback and operating-system DNS lookup are not forcibly interrupted. Slowly arriving HTTP status or header bytes and repeated low-level socket reads can also exceed an intended attempt budget before control returns to the deadline check.

Before production acceptance, test the real credentials and refresh path, both routes independently, the approved failure cases, backup capacity, a later successful primary request and the application's behavior when both routes fail. Set the recovery-time target and acceptable failure rate before the test. Keep measured results separate from configuration intent.

See [identity and access](identity-and-access.md), [implementation plan](implementation-plan.md) and [the architecture decision](adr-001.md).

Public documentation checked October 13, 2026. Deployment-specific support and live validation remain separate checks.
