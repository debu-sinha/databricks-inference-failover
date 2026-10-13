# Review plan for routing and setup

This pass covers the shared-routing proposal, README, first-time reader guide, setup and identity guidance, acceptance plan and architecture diagrams. It does not change runtime code or complete deployment acceptance.

## What a reader must be able to answer

1. What is the proposal, and where does the library run?
2. Can the application run as a Databricks App, and what is still missing from this repository to do that?
3. How does the person sign in, how does the backend authenticate, and whose permissions does Databricks check?
4. What must the operator configure before the first request?
5. What changes between hosted pay-per-token, eligible provisioned throughput and an external model provider?
6. What causes a backup request, and what happens on the next request?
7. What has actually been tested, and what is still required for regional DR?
8. How can applications keep one shared API address, and which parts of that design are proposed rather than shipped here?
9. What does Databricks provide, what does this library implement, and what must the gateway and operations teams supply?

## Checks before publishing

| Check | Pass criteria |
| --- | --- |
| Public product sources | Current Azure documentation supports model-mode, identity, grant and processing-location statements. Named model availability has a date and an official source |
| Code comparison | Configuration names, authentication flow, failure decisions and excluded features match the published implementation |
| Setup completeness | Manual prerequisites, responsible roles, route settings and ordered test steps are explicit. No command is presented as infrastructure creation when it only makes a request |
| First-time reader | Independent reviewer can answer the questions above without the prior conversation |
| Architecture fit | Central routing is evaluated before adding the library to every application. The shared gateway is clearly not deployed by this repository. Backend fallback, workspace-entrypoint failure and gateway availability remain distinct |
| Diagrams | Rendered PNGs are inspected at reading size. Arrows and labels match the proposal. No diagram labels an unverified workspace route as an independent inference region |
| Security and tone | No secrets, customer names, private sources or unsupported claims. Plain wording, normal keyboard punctuation and no marketing language |
| Repository checks | Relative links resolve, figures load, Python lint, format, type checks and local tests remain green. No new live test claim is added without execution evidence |
| Final save | Independent review findings are resolved, the exact final diff is checked, and the remote commit is verified after publication |

Use the existing [validation record](validation.md) for executed code results. The [acceptance plan](acceptance.md) still governs production identity, real faults, recovery, load and topology. A passing explanation review does not close those checks. Keep review receipts and environment-specific evidence outside the repository.
