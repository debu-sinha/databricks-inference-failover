# Identity and access

There are two separate identities in this design: the person using your application and the principal calling Databricks. Decide which principal should call the model before enabling fallback.

For a first-time explanation and a request-flow diagram, read [how authentication works](start-here.md#how-authentication-works). The generic OAuth example and a Databricks App's automatic service principal are different integration choices. This repository has not deployed or tested a Databricks App.

## Recommended starting pattern

Use application authentication for the user, application authorization for the requested action and data, and a dedicated service principal for backend inference. A Databricks service principal is an application identity with its own resource permissions. [Service principals](https://learn.microsoft.com/en-us/azure/databricks/admin/users-groups/service-principals).

| Boundary | Decision |
| --- | --- |
| User to application | Verify the user's session through the application's identity provider. Check tenant, feature and data access in the backend. |
| Application to Databricks | Use the destination's approved Databricks credential. In the service-principal pattern, Databricks authorizes that principal, not each application user. |
| Databricks to model destination | Unity Gateway checks the model service and its owner's access to referenced destinations. |

The application must not treat a client-supplied user ID or request tag as proof of identity. Derive any audit correlation from the verified session. Keep Databricks bearer tokens in the backend. Do not return them to the browser or put them in URLs.

## When applications call a shared routing service

A shared gateway adds another access boundary. The application authenticates to that service under an agreed machine or delegated-user contract. The shared service verifies the caller, applies the caller's approved model and tenant policy, and selects an allowed route. It then authenticates separately to the chosen Databricks workspace.

The shared service must not accept an arbitrary workspace URL, model-service name, tenant ID or privileged credential from an untrusted caller. Derive routing permissions from verified identity and controlled configuration. A backup must stay within the same caller's approved model and data-processing policy. A routing failure does not grant broader access.

When the shared service uses a service principal, Databricks checks that principal's grants. The caller's application identity is not automatically a Databricks end-user identity. The service must preserve its own trusted audit mapping without treating a user header as authorization. If individual Databricks user enforcement is required, design and test delegation as described below.

The Python callback example only covers the final outbound Databricks credential boundary. It does not authenticate callers to a shared gateway, exchange their tokens, or configure APIM managed identity. Those are integration work with their own tests. See [shared-routing acceptance](acceptance.md#f-shared-gateway-integration).

## Token acquisition and refresh

Databricks-managed service principals support OAuth M2M for unattended applications. Supported unified-authentication clients manage token generation and refresh. A manually obtained token expires after one hour and needs renewal. Workspace-issued tokens are limited to that workspace. Account-issued tokens have different scope, so do not assume tokens are interchangeable. Microsoft Entra-managed service principals use a separate documented authentication path. [OAuth M2M](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/oauth-m2m).

The library calls `Destination.token_provider` before that destination's attempt. This callback returns a bearer-token string. It is an integration hook, not an OAuth implementation. Your application must provide acquisition, refresh, expiry handling and secure storage. Use a reviewed credential library with explicit host and identity configuration. Give acquisition its own timeout because the synchronous callback cannot be forcibly interrupted by this client.

Maintain a separate credential context for each destination. Bind the primary callback to the primary host and the backup callback to the backup host. A single approved principal can be provisioned in both workspaces, but access must be checked in each. Separate principals may be preferable when policy calls for stronger isolation. Store secrets in the deployment's secret manager and rotate them through the existing operations process. These are recommended controls, not resources created by this repository.

## If Databricks must see the individual user

A delegated-user design needs an approved OAuth flow that yields the user's Databricks credential for the intended resource. Azure Databricks documents U2M OAuth and requires a custom OAuth application for clients outside its built-in tools. [User OAuth](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/oauth-u2m).

Your application's SSO session is not automatically forwarded or exchanged by this library. Do not send an application session cookie, arbitrary identity-provider token or user ID in place of a Databricks bearer token. Implement and test the supported delegation flow separately, including expiry and access to both destinations. Never silently replace a denied user request with a more privileged service-principal call.

## Grants to verify on both routes

For each configured workspace and model service, check the caller's workspace access and the effective `USE CATALOG`, `USE SCHEMA` and `EXECUTE` grants. A service owner's destination permissions are a separate requirement. Model services use the owner's privileges for their referenced destinations. The caller does not need direct destination grants just to invoke the service. [Model service governance](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-services#governance-and-privileges).

Use only the permissions required for inference. The runtime caller should not need to create services, change routes or grant access. Match allowed models, data policy and application authorization on primary and backup before enabling fallback. The client stops on token-acquisition failures and on HTTP 401 or 403. It must not be used to escape an access denial.

## Audit and acceptance checks

Log operation ID, attempt destination, HTTP status, outcome and elapsed time. Do not log bearer tokens, client secrets, prompts, outputs or complete upstream error bodies. The returned result contains model output, so logging the whole result object would expose content. Apply the application's retention and access policy to its logs.

Before release, test expired and revoked credentials, a denied user, a denied service principal, missing backup grants and secret rotation. Confirm that errors remain visible and that no credentials or prompt content reach logs. Test token refresh against both intended workspaces. Local policy tests do not establish live OAuth behavior.

Public documentation checked October 13, 2026. The application identity integration and workspace grants are not provisioned or live-validated by this reference client.
