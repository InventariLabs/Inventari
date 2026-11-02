# Documentation Index

The documents in this directory are organised by the reader they serve. Start
at the path that fits you; the technical reference below is design detail that
ships with the repository, not a guide.

- **Using the app** — you have an account and want to get things done.
- **Running and maintaining it** — you host an instance and keep it healthy.
- **Building on Inventari** — you create an application or extend a workflow with your own module.
- **Contributing to Inventari** — you improve the platform or its included modules.

## Using the app

| Document | Topic |
|---|---|
| [Live demo](https://demo.inventari.app) | Try the app in the browser: an organization of your own, wiped every night — not for real data |
| [Getting started](../README.md#quick-start) | Install and run your own instance, first login |
| [USER_GUIDE.md](USER_GUIDE.md) | The end-user guide, illustrated with screens of the demo: locations, products, scanning, documents, reports |
| [GALLERY.md](GALLERY.md) | Screens of the running application, module by module |
| [FOCUS_MODE.md](FOCUS_MODE.md) | Showing a single module (Settings → My modules) |

## Running and maintaining it

| Document | Topic |
|---|---|
| [QUICK_DEPLOY.md](../QUICK_DEPLOY.md) | Deploy to a VPS with automatic HTTPS in six steps |
| [DEPLOYMENT.md](../DEPLOYMENT.md) | Full deployment guide — [updating](../DEPLOYMENT.md#updating), [database backups](../DEPLOYMENT.md#database-backups), [putting a backup back](../DEPLOYMENT.md#putting-a-backup-back), [rebuilding on a new server](../DEPLOYMENT.md#rebuilding-on-a-new-server), [troubleshooting](../DEPLOYMENT.md#troubleshooting) |
| [SECURITY.md](../SECURITY.md) | Reporting a vulnerability, supported versions, responsible disclosure |
| [SCALING.md](SCALING.md) | Running more than one backend replica |
| [SCALE_REPORT.md](SCALE_REPORT.md) | What one organization of a hundred thousand products costs in response time, measured on a 4-core VPS |
| [CLI.md](CLI.md) | Command-line reference for `manage.py` |
| [DEMO.md](DEMO.md) | Running a public demo instance |
| [OFF_DATABASE_SETUP.md](OFF_DATABASE_SETUP.md) | Open Food Facts database import |
| [GDPR_MANUAL_PROCEDURE.md](GDPR_MANUAL_PROCEDURE.md) | Answering a data subject's request: exporting or erasing one person's data |

## Building on Inventari

The included warehouse, kitchen, equipment and production applications are
modules on a shared core. Start with a package of your own, or adapt an
existing workflow through its public extension points.

| Document | What it helps you do |
|---|---|
| [Build on Inventari](../README.md#build-on-inventari) | Understand the platform through the applications built on it |
| [Module Quick Start](../MODULE_QUICKSTART.md) | Generate, develop, test and install your first module |
| [Lot certificates example](../examples/lot_certificates/README.md) | Extend the warehouse with fields, a posting rule and a picking strategy |
| [Module guide](../MODULES_GUIDE.md) | Work with Core data and define your module's own data and behavior |
| [Frontend module guide](FRONTEND_MODULE_GUIDE.md) | Add pages, navigation and contributions to existing screens |
| [Advanced module guide](MODULE_ADVANCED_GUIDE.md) | Connect lifecycle hooks, events, interceptors and background work |
| [Module testing](MODULE_TESTING_GUIDE.md) | Test your package against Inventari |
| [Module capabilities](MODULE_CAPABILITIES.md) | Declare the resources your module uses |
| [Module versioning](MODULE_VERSIONING.md) | Version your package and declare its platform requirements |
| [Module naming](MODULE_NAMES.md) | Choose names that work with the platform |
| [Compatibility policy](subsystems/CONTRACTS_STABILITY.md) | Identify stable and experimental interfaces |
| [Module licensing](../MODULE_LICENSING.md) | Read the terms for licensing and distributing a module |
| [OpenAPI schema](api/openapi.json) | Inspect the current REST API (`make generate-openapi` refreshes it) |
| [Error responses](api/ERRORS.md) | Handle the error envelope and refusal codes |

## Contributing to Inventari

[CONTRIBUTING.md](../CONTRIBUTING.md) covers the development environment,
repository workflow, coding standards and pull requests for changes to the
platform and its included modules.

## Technical reference

Design detail that ships with the repo (ERD, ADRs, subsystem and purpose docs).
Authoritative for maintainers; not a stability contract for integrations.

| Document / directory | Topic |
|---|---|
| [ERD.md](ERD.md) | Entity-relationship diagram |
| [STOCK_MUTATION_REPORT.md](STOCK_MUTATION_REPORT.md) | Mutation testing of the stock posting code (`make mutate-stock`) and the last full run |
| [TECHNICAL_DECISIONS.md](TECHNICAL_DECISIONS.md) | Technical decision log: the decisions without a dedicated ADR, and the original rationale behind several ADRs |
| [adr/](adr/) | Architecture Decision Records |
| [subsystems/](subsystems/) | Core subsystem references (analytics, printing, webhooks, …) |
| [purpose/](purpose/) | Purpose cards — whose job each module and Core area serves, and where it ends |
