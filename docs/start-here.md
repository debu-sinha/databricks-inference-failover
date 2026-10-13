# Start here: what you need to build

The target is one API endpoint for your applications, with routing and failover managed centrally. Applications request the same approved model. A shared routing layer chooses the primary or backup Databricks route without requiring regional routing logic in every application.

The repository contains a Python client, not that shared API. Evaluate your existing gateway first. If it can provide the required routing, you might not need this library in production. If a shared Python backend is needed, it can import the library. That backend, its API and its deployment still have to be built and tested.

![One shared entrypoint with routing outside the regional Databricks services](shared-routing.png)

**Current status: reference implementation.** The [test record](validation.md) includes real calls and an unresolved concurrent-request result. Production identity, actual upstream failure and recovery, the intended model and regional independence still need validation.

## The terms used here

| Term | Meaning in this guide |
| --- | --- |
| Application | Your product's web service, API backend or worker |
| Databricks App | An optional Databricks service for hosting an application |
| Shared routing layer | The gateway or backend that presents one API and owns routing across Databricks workspace entrypoints |
| Workspace URL | The Databricks address selected for a request |
| Model service | A named Unity Gateway resource that routes a request to a model. Its name has the form `catalog.schema.service` |
| Service principal | An application identity with its own Databricks permissions |
| Access token | A short-lived credential presented with an API request |
| Pay-per-token, or PPT | Hosted model access billed by token usage |
| Provisioned throughput, or PT | Serving capacity configured for an eligible model |

## Choose where routing will run

If you already use Azure API Management, assess its backend pools, circuit breakers and policies first. Validate the Databricks request format and authentication on each route. A backend pool does not configure model capacity or prove regional independence. Its circuit-breaker behavior is also different from this library's per-request fallback. [APIM backends](https://learn.microsoft.com/en-us/azure/api-management/backends).

The Python library does not run inside APIM policies or Unity Gateway. It runs in a Python backend or worker that imports it. It needs no notebook or Spark cluster. Do not create another gateway just to use the library if the existing gateway can meet the requirement. [Architecture decision](adr-002.md).

A Databricks App can host Python application code. If you choose it, you still need an application entry point, dependency configuration, deployment, permissions and operating setup. This repository provides the library and command-line examples, not those App deployment files. [Databricks Apps](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/), [App structure](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/key-concepts).

**If the shared routing layer stops, applications lose that path.** Its entry URL, hosting, identity, secrets and network dependencies belong in the recovery plan. If a Python backend hosts the library, its availability is part of that plan too. Moving a model request cannot restore a stopped gateway, application or its data.

## How authentication works

For the service-principal design, caller identity and Databricks identity are separate. Your application authenticates its user, and the shared API authenticates the application calling it. The routing layer uses an approved Databricks identity for each workspace. Databricks checks that identity's permissions. The application and shared API still enforce tenant, feature and data access.

The diagram below shows the optional Python-backend implementation. It does not mean each application must import the library. APIM authentication must be configured and tested separately.

![User sign-in and backend credentials are separate](request-identity.png)

The [OAuth example](../examples/application_oauth.py) works as follows:

1. Your deployment supplies a workspace URL, service name, service-principal client ID and OAuth secret for each route.
2. The Databricks SDK uses that route's credentials to obtain a short-lived access token. Its credential provider manages token refresh.
3. The library sends the token with the model request. The secret itself is not sent in the inference request.
4. If backup is attempted, the library asks the backup credential provider for its token. A primary workspace token is not reused as a backup workspace token.

The client ID identifies the application identity. The secret proves control of it. The access token is the credential used for the API call. Authentication establishes who is calling. Permissions determine whether that identity may invoke the service. [OAuth M2M](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/oauth-m2m).

The administrator must grant the caller workspace access and `USE CATALOG`, `USE SCHEMA` and `EXECUTE` for the model service. The service owner's access to the underlying destination is a separate check. Repeat the access checks on both routes. [Model-service grants](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-services#grant-access-to-a-model-service).

### If the host is a Databricks App

Databricks automatically gives an App its own service principal. App authorization and user authorization are separate supported models. In the first, calls use the App's identity. In the second, calls use the signed-in user's delegated identity. [Apps identity model](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/key-concepts#app-authorization).

This repository's generic OAuth example reads explicit `PRIMARY_` and `BACKUP_` credentials. It does not automatically wire up the App's assigned service principal or grant it access to another workspace. That integration needs configuration and live tests. Do not assume the App's forwarded user token works in a second workspace. See the workspace limit in [Apps authorization](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/databricks-apps/auth#user-authorization).

If every user's Databricks permissions must be enforced individually, design and test user delegation for both destinations. Never replace a denied user request with a more privileged service-principal request. The library does not perform user login or delegation. See [identity and access](identity-and-access.md) for the details.

## Choose the model setup before configuring fallback

"Closed model" describes access to the model's weights. PPT and PT describe how it is served. They are different questions. As of October 13, 2026, Azure's ADI documentation lists GPT-6 Luna, GPT-6 Sol and GPT-6.1 Sol as **pay-per-token only**. Do not plan to deploy these exact models as PT endpoints. Confirm the full model name, since another version can have different support. [ADI Services](https://docs.databricks.com/adi).

| Route choice | What your team prepares | What still needs proof for regional failover |
| --- | --- | --- |
| Databricks-provided model on PPT | Confirm availability and any ADI eligibility, find the approved service in each workspace, grant access, and confirm quota and permitted processing locations. You do not deploy the hosted model's GPUs | Whether the two routes use independent model capacity and which failure each route survives. Two workspace URLs alone do not answer this |
| Eligible model on PT | In each approved region, prepare the workspace and regional metastore, deploy the same approved model/version with enough capacity, and configure a region-local model service referencing its PT endpoint | Actual endpoint placement, independence, model compatibility and backup capacity under the expected load |
| Your external model provider | Prepare the provider deployments, capacity, credentials and network access. Configure model provider services and the model services that use them | Whether both Databricks routes ultimately call the same provider deployment, plus the provider's regional and recovery guarantees |

Setup references: [hosted model access](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/), [PT deployment](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/deploy-prov-throughput-foundation-model-apis), [external providers](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-provider-services).

A **region** is a cloud location, such as East US. A **Geo** groups regions for data residency. Hosted inference can run outside the workspace region under the applicable processing-location rules. An East workspace is therefore not evidence of an East model backend. Obtain the exact supported topology before labeling the design regional DR. [Processing locations](https://learn.microsoft.com/en-us/azure/databricks/machine-learning/foundation-model-apis/compliance), [Geographies](https://learn.microsoft.com/en-us/azure/databricks/resources/databricks-geos).

For the PT design, use one model service and its PT destination in each regional metastore. Keep switching between the workspace entrypoints in the customer-managed routing layer. Do not configure one model service as though it can reference PT destinations across those metastores. Regional metastores govern the objects and grants. They do not prove where hosted PPT inference runs. [Regional metastores](https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/create-metastore).

## What you set up, in order

The diagram shows the optional Python client path. The steps below also apply when an existing gateway owns routing directly.

![Setup and operating responsibilities](setup-ownership.png)

1. **Define the contract and failure to cover.** Agree the single API, same approved model/version, recovery time and permitted locations. A model request failure, loss of a workspace entrypoint and loss of the shared gateway are different failures.
2. **Prepare the model routes.** The workspace and model administrators complete the PPT, PT or external-provider setup above. Confirm both routes serve the required API and model contract. If using this library, both must support its Unified Responses text-only request shape.
3. **Prepare identity and access.** Supply approved identities, grants and secure credential acquisition for both routes. Configure caller authentication at the shared API separately. A person's credentials can be used for an authorized lab test, but that does not test production M2M authentication.
4. **Configure shared routing.** The gateway owner configures route mapping, credentials, failure criteria, safe replay and response handling. A shared Python backend can use the library if needed. Keep routes under deployment control, not end-user input. Do not silently substitute another model.
5. **Prove both routes work independently.** Run a primary baseline, then a backup baseline, using the intended model, API and runtime identity. Verify actual token renewal before unattended use.
6. **Test the agreed failures and recovery.** Use an approved isolated fault, then verify backup completion, restoration and later primary use. Test both routes failing, expected load and shared-gateway dependencies. The local synthetic 503 example does not complete this step.
7. **Accept and operate the deployment.** Assign monitoring and incident ownership, alerts, rollback, backup capacity and gateway availability. Define the error returned when both routes fail and who approves restored primary traffic. Use the [acceptance plan](acceptance.md) before enabling production traffic.

Complete this worksheet privately before executing the examples. Do not put secrets in it.

| Setting or evidence | Primary | Backup |
| --- | --- | --- |
| Exact Azure workspace URL | Required | Required |
| Existing three-part model-service name | Required | Required |
| Model/version, or alias and version-change policy | Required | Required |
| Serving mode and backing destination | Required | Required |
| Approved processing locations and independence evidence | Required | Required |
| Available quota or provisioned capacity | Required | Required |
| Caller identity and verified grants | Required | Required |
| Secret-manager reference, never the secret | Required | Required |
| Successful independent request with intended identity | Required | Required |

## Who supplies each part

| Part | What it supplies | What you still prepare |
| --- | --- | --- |
| Databricks platform | Model serving, service permissions and supported destination fallback inside a model service | Two approved routes, correct model/version, grants, quotas or capacity, and processing-location evidence |
| This library | One primary attempt, at most one backup attempt, explicit failure policy and attempt metadata | A Python caller, token providers and replay approval. It supplies no HTTP server, model verification or persistent circuit breaker |
| Shared routing layer | The proposed single API, caller authentication, model mapping and central route policy | Configure and test the chosen gateway or backend. No such deployment is supplied here |
| Operators | Provisioning, credential lifecycle, monitoring, incident response and recovery | Prove gateway availability, both routes, expected load, failure isolation and restoration |

`PRIMARY_SERVICE` and `BACKUP_SERVICE` select existing services. They do not create models or choose their serving mode. Follow [the setup commands](setup.md) to populate the environment variables and run the examples.

Fallback starts disabled. The example CLI can set `--allow-status 503` and `--replay-safe`. Timeout values and replay after uncertain transport failures are configured through `Policy` in the calling Python application. The CLI does not expose those as flags. A regional connection failure might therefore stop rather than try backup under the default settings. Review duplicate-call risk before changing this. Authentication failures never trigger backup. See the [full failure table](failure-policy.md).

Unity Gateway can also perform destination fallback behind the workspace entrypoint. Configure it separately and review the combined attempts and latency. This library does not create or edit that routing. [Gateway routing](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/configure-traffic-splitting).

With this library, exhausted attempts raise `FailoverError`. The shared API must map that to its agreed error response. Every new library operation starts at primary, so the library does not hold traffic on backup or decide that primary has recovered. A gateway's circuit breaker and restoration policy need their own tests.

The supported library request is synchronous, text-only and nonstreaming. Streaming, tools, conversation persistence, exactly-once execution and load generation need separate integration work. Our live calls used GPT OSS 20B and a user identity. They do not validate GPT Luna/Sol, service-principal authentication, APIM integration, a shared HTTP API or a Databricks Apps deployment.
