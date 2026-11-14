# MCP Server

## Job
"Let the agent I already use work with my inventory without me copying numbers into it."

## Whose job
The person who issues the API key. The agent is theirs to connect and disconnect; the workspace
administrator only decides whether the module is on and which roles may hold `mcp_server:use`.

## Inside the boundary
The Model Context Protocol over Streamable HTTP, revision 2026-07-28, at one endpoint
(`/api/v1/mcp-server/mcp`). A request authenticates with an API key from **API Keys**, acts only in
the key's organization, and sees what that key's permission list allows: `items:read` for stock,
batches and expiry, `locations:read` for the location tree, `items:write` for the two writes. The
seven read tools (`search_items`, `get_item`, `list_locations`, `get_location_tree`,
`get_stock_levels`, `list_lots`, `get_expiring_soon`) and the two resources (workspace overview,
location tree) answer from CoreAPI, so the stock number, the tenant scope and the journal actor stay
in one place. The two guarded writes do the same: `create_item` opens a record through the create
service, with its opening movement and history reason, and `correct_stock` follows the stock-take
posting path — the group locked, one quantity write that posts the movement, the register's copy
through **Warehouse**, the reason in the history and the organization journal.

The host and origin allow-list is part of the boundary: an organization names the deployed hosts it
answers on, and the SDK's transport security refuses every other `Host`/`Origin`.

## Outside the boundary
- Who a key belongs to, what it may do, and when it stops → **API Keys** (including the
  owner-membership rule and the credential-change marker)
- The stock numbers, shelves, batches and expiry dates → the Core (items, locations, stock, queries)
- Change notifications, document receipts and issues → **Webhooks** and **Warehouse**, not here
- The agent's own memory, planning and conversation → the agent's client, not the workspace

## Own concepts / Borrowed
**Own:** the MCP endpoint, its tool catalogue, the tool result shapes and the request-scoped
identity the tool handlers read.
**Borrowed:** the API key and its permissions, the user context it acts as, every record it reads,
and the SDK's transport security.

## Deliberately not done
- **No document writes.** A receipt, an issue or a transfer is a document with its own screen,
  approval and printout, and it stays in **Warehouse**. The two writes here are the smallest pair
  that lets an agent correct what it was asked about: a new record and a counted quantity with a
  reason. They are not a second document workflow.
- **No administrative tools.** A key cannot list users, change settings, manage modules or issue
  other keys through MCP, so a leaked key cannot escalate through the endpoint.
- **No OAuth in phase 1.** The bearer API key is the documented deviation for a self-hosted
  installation; OAuth 2.1 and protected-resource metadata wait until a hosted multi-tenant
  deployment needs them.
- **No legacy SSE transport.** The 2026-07-28 revision is POST-only; a client that still needs SSE
  is a reason to revisit, not a compatibility mode shipped by default.
- **No UI of its own.** The module has a settings card (allowed hosts and origins) and a launcher
  tile that explains how to connect; the endpoint is for agents, not a screen to operate daily.

## Switched off
The endpoint answers 401 with `WWW-Authenticate: Bearer` for every key, including one that was
valid a moment ago. The keys themselves are untouched, so switching the module back on restores
them; the API Keys screen keeps working because its own gate is the `api_keys` module.
