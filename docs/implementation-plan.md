# Implementation and review plan

This is a reference client for application-owned fallback between two explicitly configured Azure workspace routes. It is not a regional deployment or a production approval.

## Scope and assumptions

The first version sends text-only, nonstreaming requests through the Unified Responses API. Each destination must already expose the required model through an approved three-part model service. The caller confirms model compatibility, processing locations, data policy and backup capacity separately.

An operation tries primary once. A second call requires the caller to declare replay safe and explicitly allow the observed HTTP status, or explicitly allow replay after an ambiguous transport failure. There is no automatic fallback policy. Authentication and input failures do not trigger a backup call. Every new operation starts at primary.

## Dependencies and call sites

This starts in an empty repository. There are no existing production callers, inherited classes or consumers to migrate. The existing validation probe was reviewed as a design reference, but no private lab runner or internal material is copied here.

The core library uses Python 3.11 or later and only standard-library networking, TLS, JSON and dataclasses. The optional OAuth example pins Databricks SDK 0.110.0 through the `auth` extra. `FailoverClient.generate` calls the injected transport once per destination. The default transport creates one HTTPS connection per attempt and closes it in `finally`. Token callbacks are called immediately before their own destination attempt.

Audit the offline module and the public `application.py`, `application_oauth.py` and `validate_pair.py` examples when changing the library. Tests cover policy independently and the HTTP transport against a loopback server. Private live runners provide evidence only for the paths they actually execute.

## Review sequence

1. Inspect code boundaries and public call sites before edits.
2. Test primary success, backup success, exhaustion and a later operation returning to primary.
3. Test rejection of malformed configuration, unsafe credentials, redirects, oversized bodies, invalid JSON and disallowed status fallback.
4. Test ambiguous completion and deadline handling without live inference.
5. Run the offline example, package imports, formatter, lint, type checks and complete local suite.
6. Have an independent reviewer assess correctness, security, tests, API and documentation consistency.
7. Reconcile live evidence with the final candidate, exact model, identity and executed entry point. Preserve completed checks without generalizing them to another deployment. A local HTTP test cannot establish Databricks support, live authentication or regional recovery.
8. Complete each applicable row of the [acceptance plan](acceptance.md), or record its unmet prerequisite and accepting owner. Do not call a planned check passed.

## Remaining execution plan

| Stage | Work and dependency | Completion evidence |
| --- | --- | --- |
| Confirm scope | Resolve exact model, API, serving mode, application actions, recovery objective, identity and accepted load with the owners | Dated decisions and unresolved requirements in the private deployment record |
| Review final package | Audit public call sites, run clean-install checks and independent code review | Results tied to the final candidate, with material findings resolved |
| Exercise public paths | Use approved inference budget on the intended library and example entry points | Distinct results for user-identity calls, static-token examples and service-principal M2M. One does not substitute for another |
| Validate production identity | Administrator provisions approved principals and grants. Identity owner supplies secrets and a renewal window | Actual M2M primary/backup, renewal, denial and rotation results |
| Review an isolated fault | Service owner supplies a reversible test mechanism and rollback. No existing fault endpoint is assumed | Approved change plan before mutation, then actual failure, fallback and restoration evidence |
| Check application behavior | Test ambiguous completion, downstream deduplication, time budgets and supervision where required | Results for the application's accepted replay and deadline contract |
| Establish load and DR scope | Obtain placement/capacity evidence and approve load and dependency-failure tests | Measured thresholds, recovery results and known shared dependencies |
| Accept release | Compare final code, documentation, diagrams and deployment scope with receipts | Named operational owner, accepted exclusions, monitoring and rollback |

The [validation record](validation.md) remains the source for executed calls and remaining coverage. An additional inference allowance applies only to its approved routes and request limits. It does not authorize infrastructure changes or turn a user-profile test into an M2M test.

Many open checks belong to the deployment and its operators. They do not automatically require new library features. Add circuit breaking, streaming, distributed deduplication or deployment automation only after an accepted requirement and design review.

No customer deployment, resource mutation or fault injection is performed by this plan. Test results must name their actual environment and limitations.
