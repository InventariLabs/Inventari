# Core — Settings

## Job
"Decide how this workspace works — once — so that nobody has to decide it again while working."

## Whose job
An administrator. A manager sees parts of it, mostly to read. Anyone else arriving here has taken a
wrong turn, and the screen should say so before they click anything.

## Inside the boundary
The organization itself; the people in it and the roles they hold; which modules are installed and
how each is configured; the workspace mode; AI connections and which purpose each is bound to; mail
and notification settings; the audit log as the record of what was done.

## Outside the boundary
- Any actual inventory work. Nothing here adds, moves or counts a thing.
- A module's *data* — Settings owns the switch, the module owns what happens after it.

## Own concepts / Borrowed
**Own:** Organization, User, Role, permission, ModuleInstallation, ProductProfile, AiConnection,
AuditLog, SystemSetting.
**Borrowed:** the name of every module it lists.

## Deliberately not done
- **Not a second place to see stock.** A count on a settings screen is a defect, not a convenience.
- **No per-user preferences beyond language and the account itself.** Settings decides for the
  organization; personal taste is not an organization decision.
- **No editing of what the audit log recorded.** It is a record, not a document.
- **No installation-level administration** — hosting, backups, deployment. That is DEPLOYMENT.md and
  the host, not a screen.

## Switched off
Cannot be. Individual sections disappear together with the module they configure — a settings
section with no module behind it is a dead end and counts as a defect.
