# Home-server app stores

What each store asks of an application, read from its own submission guide on
2026-11-24, and what Inventari would have to provide. Quotes are verbatim from
the page named; "inference" marks a reading that no page states. These rules
change: read the guide again before a submission. The entries themselves are
not made yet.

Inventari as these stores see it: a compose stack (Caddy, Postgres 17, two
Valkey instances, PgBouncer, the FastAPI backend, the nginx frontend and a
backup sidecar), AGPL-3.0, with multi-arch (amd64, arm64) images published for
each release at `ghcr.io/inventarilabs/inventari-backend`, `-frontend` and
`-backup` (DEPLOYMENT.md, "Pulling the published images instead of building").

---

## 1. Unraid Community Applications

**Pages read**
- https://ca.unraid.net/submit/help (Submission Help)
- https://ca.unraid.net/submit/help/repository-xml (Repository XML Format)
- https://ca.unraid.net/submit/help/repository-info-xml (ca_profile.xml)
- https://ca.unraid.net/submit/help/builders (Builder Guide)
- https://github.com/unraid/unraid-community-apps-starter (starter README)
- https://unraid.net/blog/new-community-apps (22 June 2026 portal announcement)
- NOT readable: https://ca.unraid.net/submit/help/compose-packages ("Compose package contract"). It is linked from the Submission Help page, which says it "explains how Community Apps creates an immutable Compose archive for Unraid 8", but the URL returns 404 "Submission help page not found", so the compose rules could not be read. Old docs.unraid.net and unraid.github.io developer pages also returned 404.

**Quotes**
- Public repo and licence: "Make sure the repository is public and active." and "Add an OSI-approved LICENSE file at the repository root."
- Packaging format: "Your repository must contain valid template XML files. For scan success, each app entry must include either a `<Repository>` tag for Docker applications or a `<PluginURL>` tag for plugins."
- One template per container: "Use one XML file per app template." and "Ensure `<Repository>` points to a valid image repository."
- Profile gate: "If ca_profile.xml is missing, or the <Profile> section is empty, Community Apps will block submission finalization."
- Process: "Run Validate and Scan in the submission flow after each meaningful XML change."
- Example registry in the official starter template: `<Repository>ghcr.io/YOUR_GITHUB_USERNAME/example-app:latest</Repository>` (shows ghcr.io is accepted).
- Multi-container / arm64: no quote found. The pages say nothing about multi-container apps, databases, reverse proxies, or CPU architecture.

**What Inventari would need**
- A public GitHub repo (can be a new small "templates" repo, not the main one) with: `LICENSE` (OSI; AGPL-3.0 qualifies), `ca_profile.xml` (non-empty `<Profile>`), an icon, and `templates/*.xml`.
- Inference from "one XML file per app template": the classic Unraid model is one container per template, so Inventari would need separate templates for backend, frontend, backup, and users must supply Postgres/Valkey/PgBouncer themselves (typically via other CA apps) or the stack must be repackaged. The Compose route (Unraid 8) looks like the better fit for a multi-service stack, but its rules page is 404, so that is unverified.
- Pinned tag is not required by the visible rules (starter uses `:latest`); no arm64 requirement visible (Unraid is x86-64 in practice; inference).
- Blocker: not a hard rule, but the single-container template shape is the likely friction. Review is a "Validate" + "Scan" pipeline plus moderators ("so moderators can review the submission quickly"); plugins are always manually reviewed.

---

## 2. CasaOS (CasaOS-AppStore, now the ZimaOS app store repo)

**Pages read**
- https://github.com/IceWhaleTech/CasaOS-AppStore (README)
- https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/CONTRIBUTING.md
- https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/quick-start/overview.md
- https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/specs/compose-and-x-casaos.md
- https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/faq/overview.md
- https://github.com/IceWhaleTech/CasaOS-AppStore/blob/main/docs/guides/third-party-store-guide.md

Note: the repo README now reads "This repository hosts the source definitions for the official ZimaOS app store." The CasaOS name is only in the repo name; the legacy v1 zip store is still built "for compatibility". There is no separate current CasaOS-specific contribution guide found.

**Quotes**
- Process: "Fork this repository and work in your own branch." then "Open a Pull Request that explains: whether this is a new app, an update, or a docs change". CI: "Repository CI validates compose files and the build pipeline automatically on PRs."
- Packaging format: "`Apps/<App>/docker-compose.yml`: app runtime configuration and top-level `x-casaos` metadata."
- Compose rule: "compose must pass `docker compose config -q`" (the repo adds no other compose rules: "this repository does not redefine Docker Compose semantics").
- Multi-service: "`main` ... must match a service name under `services`" and "should point to the user-facing web service, not a helper container". Common mistake listed: "pointing `main` at a database container".
- Architectures: "`architectures`: recommended; array of strings; common values include `amd64` and `arm64`". Build error: "declared architecture not supported by the container image".
- Required first-app fields: top-level Compose `name`, `services`, `x-casaos.id`, `x-casaos.main`, `x-casaos.index`, `x-casaos.port_map`, `x-casaos.icon`, `x-casaos.title`, `x-casaos.category`. (List items, not a sentence.)
- Registry / pinning: "registry rate limits, digest pinning failures, or image-size estimation failures: the app keeps building when possible and the issue is reported as a warning". No quote found requiring a pinned tag, a specific registry, or a licence.

**What Inventari would need**
- A PR adding a `docker-compose.yml` for Inventari under the store's `Apps/` directory (the existing compose, trimmed) plus an `x-casaos` block (reverse-domain `id`, `main: <frontend or caddy service>`, `port_map` as a quoted string, `index`, `icon`, `title`, `category`, `architectures: [amd64, arm64]`, `version` in semver), an `icon.svg`, `thumbnail.png`, screenshots.
- Multi-container is allowed by the schema (services + `main` pointing at the web service). Inference: Caddy can stay as the `main` service, or be dropped and the nginx frontend used as `main`. Compose must pass `docker compose config -q`, so env-file/secret handling must work without a pre-made `.env` (inference).
- Published, public multi-arch ghcr.io images are required in practice because declared `architectures` are checked against the image (error on mismatch).
- No licence/maintainer rule found for app submissions (only `maintainer` in the store-level `store-config.json`). Blocker: none visible; the official store is a ZimaOS (IceWhale) product, so acceptance is at IceWhale's discretion (inference; no review criteria published).

---

## 3. Umbrel (official umbrel-apps; community store template)

**Pages read**
- https://github.com/getumbrel/umbrel-apps (README, AGENTS.md)
- https://github.com/getumbrel/umbrel-apps/blob/master/.agents/skills/umbrel-package-app/SKILL.md (the repo's current packaging rules; README says these skills "capture the current Umbrel App Store guidance")
- https://github.com/getumbrel/umbrel-community-app-store (community store template README)
**Quotes (from SKILL.md unless stated)**
- Arch: "The app must have maintained images that support `linux/amd64` and `linux/arm64`."
- Registry/pinning: "Images must be publicly pullable without registry credentials, private registry access, GitHub package permissions, or local build context." and "Pin every image as `registry/repo:version-or-commit@sha256:<digest>`."
- Multi-arch digest: "Use the multi-arch manifest-list/index digest for the tag, not an architecture-specific image digest." Also "Do not use compose `build:` in App Store packages."
- Multi-container: "Use sidecars when upstream expects separate databases, caches, workers, search, or queues; do not collapse them into one container just to reduce service count." and "Pin every image used by every service, including databases, caches, workers, migration/init jobs".
- Reverse proxy: "Define an `app_proxy` service with environment only. umbrelOS reads it to route the app `port` to your web service." and "Do not publish the web UI with raw `ports:` when app_proxy is sufficient."
- Licence: "Surface packaging risks early, especially unclear licensing, stale images, fixed public URL assumptions, manual-only setup, or broad host access." (no stated licence whitelist)
- Review/PR: "Include app screenshots and the app logo/source logo in the PR body for App Store review. Do not commit screenshots, gallery assets, or icon assets for official App Store submissions" ; manifest: "Set `submission` to the pull request URL."
- Store standard (README): "Every app package should be understandable from the browser after install."
- Community store alternative: "These additional app stores allow developers to distribute applications without submitting to the Official Umbrel App Store."

**What Inventari would need**
- Official store: a directory `inventari/` with `umbrel-app.yml` (manifestVersion, id, name, version, tagline, description, developer, website, repo, support, port, `gallery: []`, submitter, submission) and `docker-compose.yml`, plus a PR with screenshots and logo. Every image (Postgres, 2x Valkey, PgBouncer, backend, frontend, backup) pinned `tag@sha256:<multi-arch index digest>`; all public and multi-arch. The `lint:apps ... --check-images` linter checks pinning, public pullability, multi-arch.
- Caddy: Umbrel supplies the proxy. Inference: drop Caddy, expose the nginx frontend through `app_proxy` (`APP_HOST`, `APP_PORT`), and have no host `ports:`. Secrets should come from `derive_entropy` in `exports.sh`; data under `${APP_DATA_DIR}/data/...`.
- Backup sidecar: Umbrel does its own app-data backup; a sidecar that writes dumps is allowed but not required (inference). Host Docker socket must not be mounted (quote: "App Store packages must not mount the host Docker socket").
- Blockers: none structural; work = reshaping compose (drop Caddy, bind-mount data, pin digests, per-install secrets) and a maintainer/user-facing first-run experience with no CLI. Fast path with no review: a community app store repo from the template (you own it, users add its GitHub URL).

---

## 4. YunoHost apps catalog

**Pages read**
- https://doc.yunohost.org/dev/packaging/ (Application packaging)
- https://doc.yunohost.org/dev/packaging/manifest (manifest.toml)
- https://doc.yunohost.org/dev/packaging/publish ("Publishing your app on the catalog")
- https://doc.yunohost.org/dev/packaging/policy (Catalog policy)
- https://github.com/YunoHost/apps (README: how to add an app)
- https://forum.yunohost.org/t/yunohost-docker-containerized-app-packaging/27900 (forum, informal)
- Note: yunohost.org/en/packaging_apps_guidelines redirects to doc.yunohost.org and then 404s; the docs were restructured under /dev/packaging/.

**Quotes**
- Licence: "The rule of thumb is that we only include software licensed under a free-software license in the official app catalog." (Policy page.) Manifest: "only apps based on free software will be accepted in the official YunoHost app catalog". AGPL-3.0 qualifies.
- Exclusion criteria (policy page): "are overly complex to deploy or resource-hungry compared to their features". (The team "may make exceptions ... on a case-by-case basis".)
- Packaging format: "packaging_format ( int ) is the packaging version format used to package this app. Newly packaged apps are strongly encouraged to use the new "v2" format". Packages are bash scripts + manifest.toml using helpers/resources (apt, system_user, install_dir, permissions, database, etc.), not compose.
- Architectures: "architectures : "all" OR a list of supported archs using the dpkg --print-architecture nomenclature, i.e. among : amd64 (= x86 64bit), i386 (= x86 32bit), armhf (= ARM 32bit), arm64 (= ARM 64bit)"
- Submission: "For your app to be made available to everybody, you should make a pull request that adds your app inside the apps.toml" and "The level key is not to be set manually by maintainers." Repo README: "Create a Pull Request" after editing `apps.toml`, adding a square logo under `logos`.
- Docker: no quote found in the official docs. A forum reply by a community contributor (not an official rule): "I believe the short answer is : no, it's a hell of development work to integrate all this stuff and the various use cases. Instead, when it's available, we prefer to package apps with a native installation". Another forum post quotes a team member: "Docker is another pandora's box. Sure we can have one app using Docker, but then we'll have another, and another".
- AI policy (repo README): "It has been decided to reject generated packages that do not follow the `example_ynh` template app."

**What Inventari would need**
- A native YunoHost package (separate `inventari_ynh` repo: `manifest.toml`, `scripts/{install,upgrade,remove,backup,restore,change_url}`, `conf/` for nginx/systemd, `doc/`, `tests.toml`), then a PR adding it to `apps.toml`. The ghcr.io images are not used by this route.
- Inference: because YunoHost's nginx is the reverse proxy and apps share the system's Postgres/redis, a package would install the FastAPI backend (Python venv, systemd service) and the built frontend as static files from a release tarball (resources.sources.main with sha256), use the `postgresql` resource, and skip PgBouncer/second Valkey/Caddy. That is a second distribution of the app, not a repackaging of the compose stack.
- Blockers: strong: no official Docker support (forum statement, informal); compose format is not accepted in any documented form. The "resource-hungry/overly complex" clause (two Valkeys, PgBouncer, sidecar) works against it. Official catalog ranks quality by an automated CI "level"; you cannot set it.
- Unofficial option: apps outside the official catalog can still be installed with `yunohost app install <url_to_git_repo_ynh>` (policy page).

---

## 5. TrueNAS apps (truenas/apps, `ix-dev/community` train)

**Pages read**
- https://github.com/truenas/apps (README)
- https://github.com/truenas/apps/blob/master/CONTRIBUTIONS.md (contributors guide, ~1500 lines; includes the "Apps Catalog Inclusion Policy")
- https://github.com/truenas/apps/blob/master/.github/pull_request_template.md (points to `app_addition.md`; the app_addition template itself was not read)

**Quotes**
- Format: "This repository contains the Docker-Compose based App catalog used by TrueNAS systems to render and update the Apps catalog." Contributors write "metadata files (`app.yaml`), configuration schemas (`questions.yaml`), and Jinja2 templates (`docker-compose.yaml`)".
- Where: "All new contributions should target the `community` train." and "You should only modify files under `/ix-dev/` or `/library/` directories."
- Images: "Prefer `ghcr` over `docker.io` for images." and "Keys for the images must always end with `image`." Non-SemVer tags need a renovate regex ("If the versioning of an image is not SemVer, a custom versioning regex must be added in the renovate-config.js file").
- Multi-container: library helpers exist for dependencies: `deps_postgres.py` ("PostgreSQL database"), `deps_redis.py` ("Redis cache"), `deps_mariadb.py`, `deps_perms.py`. Example: `tpl.deps.postgres("postgres", "postgres_image", pg_config, perms)`; containers added with `tpl.add_container(...)`. Healthchecks and `depends_on` are supported.
- Review: "A maintainer will review your PR" and "Reviewer will upload icons/screenshots". "Open a draft PR: This allows maintainers to catch any wrong directions early".
- Inclusion: "The TrueNAS team maintains this catalog and reserves the right to reject, remove, or unpublish any application at its sole discretion, with or without a stated reason." and "Meeting the technical requirements in this repository does **not** guarantee inclusion."
- Run-as: "Run as Non-Root: Always define `run_as_context` with a non-root user".
- Arch / licence: no quote found on arm64 (the only mention is an example rendered file with `platform: linux/amd64`, which reads as showing the catalog is amd64-oriented; inference). Licence appears only as a field in the PR template ("Links to upstream repository, documentation, license, and version"); no whitelist found.

**What Inventari would need**
- A PR adding `ix-dev/community/inventari/` with `app.yaml`, `ix_values.yaml` (pinned images: backend, frontend, backup, postgres, valkey/redis, pgbouncer), `questions.yaml` (the UI form: ports, storage, secrets, timezone), a `docker-compose.yaml` Jinja2 template using the TrueNAS library, `templates/test_values/*.yaml`, `README.md`, icon and screenshots (reviewer uploads to the CDN). The existing compose file cannot be submitted as is; it must be rewritten as templates.
- Inference: TrueNAS gives Postgres and Redis helpers, but not Valkey or PgBouncer, so either the Valkey/PgBouncer containers are added through `add_container` (generic) or the stack is simplified to what the library supports. Caddy would not be needed: TrueNAS exposes a port and a portal. Data goes through TrueNAS-managed storage (ixVolume or host path) rather than compose volumes.
- Blockers: no technical "single container only" rule, but it is the heaviest rewrite of the five (Jinja2 + schema), inclusion is discretionary, and there is no stated arm64 requirement (inference: TrueNAS SCALE is x86-64, so ghcr multi-arch is fine but unused).

---

## Summary

| Store | Packaging | Multi-container OK? | arm64 | Main thing Inventari must provide |
|---|---|---|---|---|
| Unraid Community Apps | One Docker template XML per container, in a public repo with OSI licence + `ca_profile.xml` (Compose package rules page was 404, unread) | Not addressed in readable docs; classic model is one container per template (inference) | Not mentioned | A templates repo: `LICENSE`, `ca_profile.xml`, icon, one `templates/*.xml` per image |
| CasaOS (ZimaOS store repo) | `Apps/<App>/docker-compose.yml` + top-level `x-casaos` block, PR to the store repo | Yes (multiple services; `main` must be the web service, not a database) | Recommended field `architectures`; checked against the image | PR with compose + x-casaos (id, main, port_map, icon, title, category, architectures, version) + assets |
| Umbrel (official umbrel-apps) | `umbrel-app.yml` + `docker-compose.yml` with `app_proxy`, PR with screenshots and logo | Yes (sidecars expected; do not collapse into one container) | Required: images must support `linux/amd64` and `linux/arm64` | Every image pinned `tag@sha256:<index digest>`, public, multi-arch; drop Caddy for `app_proxy`; bind-mount data; per-install secrets |
| YunoHost apps catalog | Native package (`manifest.toml` + bash scripts), not compose or Docker | No Docker route in the docs (forum: native preferred); stack must be flattened onto the system nginx/Postgres | `architectures` field: all/amd64/arm64/armhf/i386 | A separate native `inventari_ynh` package; free licence is fine; "overly complex or resource-hungry" is an exclusion criterion |
| TrueNAS apps (ix-dev/community) | `app.yaml` + `questions.yaml` + Jinja2 `docker-compose.yaml` using the TrueNAS library, PR to the repo | Yes technically (Postgres/Redis/MariaDB helpers, `add_container`), but must be rewritten as templates; inclusion is at TrueNAS's discretion | Not stated; examples are `linux/amd64` | Full templated app (ix_values with pinned ghcr images, questions schema, tests, non-root `run_as_context`), icon and screenshots for the reviewer |
