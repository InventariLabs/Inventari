# Roles and permissions

Custom roles are org-scoped bundles of permission strings. A user's effective
set is resolved in this order (`resolve_permission_strings_async` in
`app/services/permissions_service.py`; the administrator bypass in step 1 is
`UserContextDTO.has_permission`, which every guard asks first):

1. A built-in **administrator** (`User.role == 'admin'`) holds everything.
2. A user with **custom roles** assigned in the organization holds exactly the
   permissions of those roles — the built-in level is not added on top.
   Assigning a role is a deliberate narrowing: a manager given a restricted
   custom role keeps only what that role grants.
3. A user with **no** custom role row falls back to the built-in level on
   `User.role`, which is where the module manifests' `default_roles` land.

## `system:config:write` is administrator access

Creating a role, changing its permissions and assigning it to a user are all
gated by `system:config:write` (`backend/app/api/roles.py`). The catalogue a
role may draw from is not narrowed by what the creator holds, so anyone with
`system:config:write` can create a role carrying `admin:access`, assign it to
themselves, and hold administrator access from that moment on.

**This is delegation working as designed, and it is written down here so it
is a decision rather than a discovery.** `system:config:write` already covers
module toggles, organization settings and the role catalogue itself; a
permission that decides which permissions exist is not meaningfully weaker
than the ones it hands out.

Three consequences worth stating plainly:

- **Granting `system:config:write` is granting administrator access.** Treat
  the two as the same when deciding who gets it. A "settings manager" role
  that is not meant to be an administrator does not exist today.
- **The audit trail is what distinguishes them.** Creating a role, changing
  its permissions, renaming it, assigning it and deleting it each write a row
  to the organization's audit log, naming the actor and what the role carried
  at that moment — `role` entries for the catalogue, an `org_member` entry for
  the assignment, since who holds what is a fact about a person. A
  self-promotion is therefore two rows an administrator can read on
  Settings → Audit Log, even though nothing refuses it.
- **The scope is the permission catalogue, not the built-in bypass.** A
  custom role carrying `admin:access` grants the permission; it does not turn
  its holder into a built-in administrator, and `require_permission` keeps its
  admin short-circuit for `User.role == 'admin'` alone. The distinction
  changes nothing about the paragraph above — the catalogue lets the holder
  grant themselves any *permission* an endpoint asks for — but it is what the
  code does, and a reader comparing the two should not find the document
  claiming more.

The alternative — capping role creation at the creator's own permission set,
the way sudo-style delegation usually works — is a product decision, not a
defect, and would change what existing installations can do. It is deliberately
not implemented.

## A settings screen opens with the key its API asks for

The settings screens are governed by the granular permissions, not by a
general "is an administrator" check: a screen opens for whoever holds the key
its own API asks for to change what the screen shows, and the sidebar lists
exactly the screens that would open. The screen and the server therefore give
a custom role the same answer. For most of the group that key is
`admin:access`, which is what `get_current_admin_user` asks; the exceptions
are the AI connections (`org:settings:write`), the role catalogue
(`system:config:write`) and the API keys (`org:settings:write`, declared by the
module's settings section). A screen that names no key stays with
`admin:access`, so one added later is closed until somebody decides otherwise.
The decision lives in `frontend/src/components/settingsAccess.ts`. A screen
that stays shut says why in the same terms: one keyed to `admin:access` says it
is for administrators, one keyed to a narrower permission names that
permission, because a custom role holding `admin:access` is an administrator
and still does not open it.

The organization write (`PUT /organizations`, `admin:access`) takes the
settings block whole, and the block carries the AI purpose bindings, which
have their own door under `org:settings:write`. That write keeps the bindings
as stored, so each choice has one door and one key.

## Who hears a notice for the administrators

Every in-app notice addressed to the administrators
(`core_api.notifications.notify_org_admins_async`, and the approvals notice
about a stage nobody can decide) goes to the members who administer the
organization by authority, not by the role's name: the built-in
administrators, and any member whose custom role carries `admin:access` or
`system:config:write` — the second because, as above, it is administrator
access under another name. Accounts that are switched off are not told.

## Where the pieces live

- `backend/app/api/roles.py` — the endpoints and their permission gates
- `backend/app/core/public_api/roles.py` — the cross-module surface
- `backend/app/services/permissions_service.py` — resolving a user's effective
  permission strings, and the organization's administrators
  (`administrators_async`)
