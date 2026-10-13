# Set up and test

Read [what you need to build](start-here.md) first. It separates hosted pay-per-token, eligible provisioned throughput and external-provider setup, explains user versus backend identity, and lists the infrastructure this library does not create.

Start locally. You need Python 3.11 or later and a terminal. You do not need a notebook, Spark cluster or Databricks credentials for the offline demonstration.

## 1. Install and run offline

```bash
git clone https://github.com/debu-sinha/databricks-inference-failover.git
cd databricks-inference-failover
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,auth]'
python -m inference_failover
python -m pytest -q
```

The demo uses synthetic responses: primary returns 503 and backup returns a completed text response. It makes no model calls. The tests cover client behavior and local transport handling. Neither establishes your workspace configuration or regional resilience. Read the [validation record](validation.md) for the checks actually completed.

## 2. Prepare two approved routes

For each workspace, ask its administrator to confirm the following:

- The exact Azure workspace URL, model service and model version to use.
- The caller's workspace access and effective `USE CATALOG`, `USE SCHEMA` and `EXECUTE` grants.
- The model service owner's access to its referenced destinations.
- The intended processing locations, allowed data, model compatibility and available capacity.
- Any existing Gateway fallback or rate limits, so application policy does not conflict with them.

In the workspace UI, open **AI Gateway**, find the approved model service and record its fully qualified `catalog.schema.service` name. For a custom service, inspect its routing and permissions. Have an administrator provision missing resources through the normal change process. The library does not create them. [Model services and permissions](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-services).

If you use the Databricks CLI, choose each profile explicitly. These are read-only checks, not provisioning commands:

```bash
databricks --version
databricks ai-gateway get-model-service --help
databricks ai-gateway get-model-service 'model-services/<catalog>.<schema>.<service>' --profile '<chosen-profile>'
```

Replace every placeholder. Repeat with the separately selected backup profile. A successful configuration read does not prove the inference caller has access. [Model Service API](https://docs.databricks.com/api/ai-gateway/v1/model-service).

## 3. Set route configuration and preview

These settings select two existing model services. They do not create resources, select PPT versus PT or pin inference to a region.

The examples read environment variables. They do not load a `.env` file. Set these four nonsecret values in your shell, replacing the placeholders with approved configuration:

```bash
export PRIMARY_WORKSPACE_URL='https://adb-<workspace-id>.<shard>.azuredatabricks.net'
export PRIMARY_SERVICE='<catalog>.<schema>.<service>'
export BACKUP_WORKSPACE_URL='https://adb-<backup-workspace-id>.<shard>.azuredatabricks.net'
export BACKUP_SERVICE='<catalog>.<schema>.<service>'
python examples/application.py
python examples/application_oauth.py
```

Preview validates the route shape and policy without reading credentials or sending network requests. The examples print destination labels rather than secrets. The client accepts exact commercial Azure workspace hosts of the form shown above. Custom domains and other clouds are outside this version. The transport needs direct outbound HTTPS and DNS access. It does not use `HTTP_PROXY` or `HTTPS_PROXY` environment settings.

## 4. Make an authorized local smoke call

Use the existing-token example only for a short local smoke test. Obtain tokens through your approved process. It does not renew them. The following launcher prompts without echoing the tokens and passes them only to the child process environment:

```bash
python - <<'PY'
import getpass
import os
import subprocess
import sys

env = os.environ.copy()
env['PRIMARY_TOKEN'] = getpass.getpass('Primary workspace token: ')
env['BACKUP_TOKEN'] = getpass.getpass('Backup workspace token: ')
raise SystemExit(subprocess.run(
    [sys.executable, 'examples/application.py', '--execute'], env=env
).returncode)
PY
```

This makes a real model request using the synthetic prompt `Reply with READY.` and can incur model charges. No fallback is enabled. A successful run reports one completed application attempt. Test the backup as primary in a separate run by swapping both route settings and the corresponding credentials. Do not mix a host with the other route's workspace token.

## 5. Prepare production identity and test OAuth M2M

Use this path for an unattended application with a Databricks-managed service principal. The optional `auth` dependency supplies SDK version 0.110.0. A successful user-identity lab test does not complete these M2M checks. If you do not have administrator access or an approved principal, give this section to the identity and workspace owners. No example creates identities, grants or secrets.

### Administrator setup

Agree whether the application will use one principal assigned to both workspaces or separate principals. Separate principals and separately stored credentials are a recommended isolation option. Do not grant account or workspace administrator rights to the inference caller.

For identity-federated workspaces, an account administrator can create the principal in the account console under **User management**, **Service principals**, **Add service principal**. Choose **Databricks managed**, enter the approved name and add it. For each destination, open **Workspaces**, select the workspace, then **Permissions** and **Add permissions**. Assign the intended principal and approved workspace entitlements. Repeat for backup. If using separate principals, assign each only where required. [Create and assign service principals](https://learn.microsoft.com/en-us/azure/databricks/admin/users-groups/manage-service-principals).

Have the object owner or authorized administrator check effective grants for the intended principal on each route:

| Object | Required inference privilege |
| --- | --- |
| Model service's catalog | `USE CATALOG` |
| Model service's schema | `USE SCHEMA` |
| Model service | `EXECUTE` |

In Catalog Explorer, inspect the catalog and schema's **Permissions** tabs. Grant missing access through the approved process. Open the model service in **AI Gateway** or Catalog Explorer, then **Permissions**, **Grant**, select the principal and `EXECUTE`, and grant access. Check inherited grants and workspace bindings too. A service owner's referenced-destination access is separate from caller access. [Unity Catalog privileges](https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/manage-privileges/), [model-service grants](https://learn.microsoft.com/en-us/azure/databricks/ai-gateway/model-services#grant-access-to-a-model-service).

### Create and store the OAuth secret

An authorized administrator opens workspace **Settings**, **Identity and access**, then **Manage** beside **Service principals**. Select the principal, open **Secrets** and choose **Generate secret**. Set the approved lifetime and API scopes, then generate it. Store the one-time secret value and client ID directly in the approved secret manager. The account-console alternative is the principal's **Credentials & secrets** tab. [OAuth secret setup](https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/oauth-m2m#step-1-create-an-oauth-secret).

Select scopes with the identity owner before creation. The [API-scope reference](https://docs.databricks.com/api/workspace/scopes) lists model-serving inference and Unity Catalog operations separately. The checked table does not explicitly map this example's `/ai-gateway/mlflow/v1/responses` route. SDK 0.110.0's M2M provider requests `all-apis`. Compatibility with a narrower secret scope has not been live-tested here. Confirm the supported scope for this exact route and SDK rather than widening access after a failure without review.

Record the secret's owner, expiry, rotation process and destination mapping without its value. Keep secrets out of Git, `.env` files in the checkout, screenshots, support logs and shell history. Let the deployment's secret manager inject values into only the application process that needs them. Treat process environments and crash dumps as sensitive. Restrict the runtime's access to its own secrets.

### Configure the application

Retain the four route variables from step 3. Add these four credential variables:

| Variable | Value |
| --- | --- |
| `PRIMARY_CLIENT_ID` | Approved primary service principal client ID |
| `PRIMARY_CLIENT_SECRET` | Its Databricks OAuth secret |
| `BACKUP_CLIENT_ID` | Approved backup service principal client ID |
| `BACKUP_CLIENT_SECRET` | Its Databricks OAuth secret |

The client ID is not the secret. For a local trial, enter only the nonsecret IDs into the shell:

```bash
export PRIMARY_CLIENT_ID='<primary-service-principal-application-id>'
export BACKUP_CLIENT_ID='<backup-service-principal-application-id>'
python examples/application_oauth.py
```

Preview performs no authentication. For one approved primary smoke call, this launcher prompts for secrets without echo and passes them to the child process:

```bash
python - <<'PY'
import getpass
import os
import subprocess
import sys

env = os.environ.copy()
env['PRIMARY_CLIENT_SECRET'] = getpass.getpass('Primary OAuth secret: ')
env['BACKUP_CLIENT_SECRET'] = getpass.getpass('Backup OAuth secret: ')
raise SystemExit(subprocess.run(
    [sys.executable, 'examples/application_oauth.py', '--execute'], env=env
).returncode)
PY
```

In a deployment where the secret manager has injected all values, the equivalent command is:

```bash
python examples/application_oauth.py --execute
```

This makes one real primary inference request and can incur charges. It does not call backup on success. To test backup independently, repeat with `PRIMARY_` and `BACKUP_` values swapped for all four suffixes: `WORKSPACE_URL`, `SERVICE`, `CLIENT_ID` and `CLIENT_SECRET`. Restore the normal mapping afterward. Keep each host, service and credential set together.

The example creates a separate explicit `oauth-m2m` configuration for each route and obtains an authentication header before its attempt. The SDK may reuse a still-valid token. Authentication is deferred until execution. This example is not for Microsoft Entra client-secret authentication.

### Test renewal before unattended use

A successful one-shot command proves neither renewal nor rotation. In the intended application process, retain both credential contexts and obtain successful primary and backup baselines. Keep that process alive across actual token expiry, then call both routes again. Record renewal and successful inference without logging token values. A restart or a user OAuth profile does not pass this test. Test denied credentials and the approved rotation procedure separately. See cases B1-B5 in the [acceptance plan](acceptance.md).

The library also accepts a user-identity token provider through `Destination.token_provider`. This can test the selected library routes using an authorized user. The generic token example accepts an already acquired token and does not refresh it. Production delegated-user access requires its own approved authentication and application-authorization design. See [identity and access](identity-and-access.md) and [production setup](production.md).

## 6. Validate fallback under an approved test plan

After both routes succeed independently, select only approved failure statuses. For a synthetic request where replay is acceptable, the example can enable backup on 503:

```bash
python examples/application_oauth.py --execute --replay-safe --allow-status 503
```

This enables policy. It does not cause a failure or prove that a backup attempt occurred. Use an approved nonproduction fault test, then inspect attempt metadata. Do not change customer quotas or interrupt a production endpoint to force a result. A 429 fallback needs explicit approval because the rate limit may be an intended admission control.

Record primary success, backup success, both failing, denied credentials, expiry and a later successful primary operation. Use the [acceptance checklist](acceptance.md). The offline demo is the safe way to practice failure handling before workspace testing.

For a real upstream failure, first prepare the [isolated fault change](acceptance.md#prepare-the-isolated-fault-change-for-review) for review. Name the dedicated service, exact reversible fault, expected status, permitted test calls, stop conditions and rollback. No fault endpoint is assumed to exist. Keep this review separate from approval to make ordinary inference calls. Test 429 and 503 policies separately, and never treat 401, 403 or 404 as failover signals.

## 7. Run the bounded pair-validation script

The [pair validator](../examples/validate_pair.py) uses the same four route variables and `PRIMARY_TOKEN` / `BACKUP_TOKEN`. It does not renew tokens. Preview needs no configuration or credentials:

```bash
python examples/validate_pair.py
python examples/validate_pair.py --baselines-only
```

After approved credentials are injected securely into the process environment, run either the two baseline calls or the full bounded sequence:

```bash
python examples/validate_pair.py --execute --baselines-only
python examples/validate_pair.py --execute
```

Use the `getpass` launcher from step 4 if supplying tokens interactively. Replace its child-command list with the validator command and selected flags. Do not paste token values into the command line.

Baselines send one real request to each route. The full sequence makes at most four real inference attempts: primary, backup, a real backup request after a locally injected primary 503, and a later primary request. Each uses a synthetic prompt and a 64-token output limit. The last two cases run only if both initial baselines succeed.

The injected primary 503 sends no primary request. It tests the application fallback branch with a real backup response. It does not simulate a regional disaster, exercise Gateway-managed fallback or establish recovery from an actual primary failure. The later primary request is another baseline, not evidence that an outage recovered.

The script prints a JSON result without prompts, outputs or credentials. Add `--receipt /absolute/private/path/new-result.json` to save a new private file. The file must not already exist. Keep environment-specific receipts outside the repository.

## If a check fails

| Result | Next check |
| --- | --- |
| Configuration error | Replace placeholders and check URL and three-part service name |
| `authentication_failed` | Check the selected auth method, host, secret and token expiry privately |
| HTTP 401 or 403 | Fix identity or grants. Do not route around the denial |
| HTTP 400 or 404 | Check API generation, service name, input and model support |
| HTTP 429 | Identify the quota or policy before enabling another route |
| HTTP 503 | Check service availability and the approved fallback policy |
| `transport_completion_unknown` | Completion is uncertain. Investigate before replay |
| `response_not_completed` | Inspect authorized service evidence for the incomplete response. Do not report success |

Keep secrets and prompt data out of support logs. Public documentation checked October 13, 2026.
