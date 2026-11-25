# MCP Server

Serves an Inventari workspace over the Model Context Protocol (Streamable
HTTP) at one endpoint:

```
POST /api/v1/mcp-server/mcp
```

The endpoint speaks two revisions of the protocol. A client that sends each
request in the 2026-07-28 envelope is answered in 2026-07-28; one that opens
with the `initialize` handshake negotiates the newest revision that handshake
has, **2025-11-25**, and the connection runs there. Both answer the same tools
and resources, so a client that reports 2025-11-25 is not talking to an older
server.

A client authenticates with an API key from the **API Keys** module. The key
carries its organization, so every tool acts only in that organization, and its
own permission list decides what the tools may do. The module is off until an
administrator enables it for the organization, and it needs **API Keys**
enabled first.

## Quickstart: Claude Code

**On the public demo** there is nothing to install: open
[demo.inventari.app](https://demo.inventari.app), click **Try the demo**, and
follow [Connect an AI agent](../../../../docs/DEMO.md#connect-an-ai-agent) —
both modules are already on in the sandbox you are given, and the key you
issue there reaches nothing but that sandbox.

The walk below starts from a disposable demo instance of your own, because a
correction changes stock and the demo is what there is to change.

1. **Rebuild the demo** (destructive: it drops the database and seeds it
   again). The command prints the administrator's e-mail and password.

   ```bash
   make demo-reset
   ```

2. **Sign in.** The demo reset switches **API Keys** and **MCP Server** on.
   On any other instance, open **Apps** and enable **API Keys**, then **MCP
   Server**.

3. **Issue a key.** Open **Settings → API Keys → Generate new key**. Name it
   something you will recognize and tick **Use the MCP endpoint** and **Add
   products and change stock levels**. **Read products and stock levels** is
   ticked already, as on every new key — leave it ticked; clicking it clears
   it. Copy the key — it is shown once.

4. **Add the server to Claude Code**, replacing `<key>` with the key. `8005` is
   the port the default compose file publishes the API on; use yours if you
   changed it:

   ```bash
   claude mcp add --transport http inventari http://localhost:8005/api/v1/mcp-server/mcp --header "X-API-Key: <key>"
   ```

   `X-API-Key` is the header Core accepts without a warning. A client that can
   send no header other than `Authorization` still works with
   `Authorization: Bearer <key>`, and Core marks that form `Deprecation`.

   On a **development** stack the address printed on the module page goes
   through the frontend's proxy, which hands the API an internal host name; the
   endpoint answers that `421 Invalid Host header`. Point the client at the
   API's own port instead — `http://localhost:8005/api/v1/mcp-server/mcp` in the
   default compose file, which publishes the API's port 8000 on the host's
   8005. A production reverse proxy passes the public host through, so there
   the address the page prints is the right one.

5. **Ask the agent to use it.** For example:

   > Search this workspace for olive oil. Tell me how much stands on which
   > shelf, then correct one record to one less than it shows and say why the
   > quantity changed.

   The agent calls `search_items`, reads the record's shelf, and calls
   `correct_stock` with a reason. `create_item` is there when the thing is not
   in the workspace yet.

6. **Check what it left.** The record's history and the organization journal
   name the reason and the API key's prefix. When **Warehouse** is on, its
   register holds one completed ADJUSTMENT document for the correction.

If this installation answers on a public address, allow that host first: open
**Apps → MCP Server** and follow its **MCP Server settings** link, then add the
host under **Allowed hosts**. The endpoint refuses an unknown `Host` header just
as the browser would. On a demo instance the seed does this for every
organization it creates, from `FRONTEND_URL`.

The walk above was measured from `make demo-reset` to the agent's answer on a
development stack: 45 seconds on 2026-11-14, with the correction registered as
`ADJ/2026/001`.

## Tools

| Tool | Permission | What it does |
|---|---|---|
| `search_items` | `items:read` | Stock rows by product name or barcode |
| `get_item` | `items:read` | One record with its batch |
| `list_locations` | `locations:read` | Locations flat, with parent ids |
| `get_location_tree` | `locations:read` | Locations nested, or one subtree |
| `get_stock_levels` | `items:read` | Quant rows or per-product shelf totals, with `total` and `has_more` |
| `list_lots` | `items:read` | Batches, status and dates |
| `get_expiring_soon` | `items:read` | The expiry window, the forecast and a shelf count |
| `create_item` | `items:write` | A record, its opening movement and the `mcp_create` history reason |
| `correct_stock` | `items:write` | A counted quantity, posted as an adjustment with a required reason |

Two read-only resources answer workspace context:
`inventari://org/overview` and `inventari://locations/tree`.

## How the writes stay inside the stock posting rules

`create_item` calls `core_api.items.create_async`, so the record's opening
stock is posted by the same service a screen uses: the movement, the cost
layer, the item history and the journal entry beside it.

`correct_stock` follows the stock-take path (`backend/AGENTS.md`, Stock Posting
Rules):

1. every `(product template, shelf)` group the call touches is locked with
   `core_api.stock.lock_async` before the first write, and the record is then
   read again under its own row lock: the difference the answer and the
   register carry is measured on the quantity that stands when the call holds
   the record, never on the read it took before waiting for the lock;
2. one `core_api.items.update_quantity_async` sets the quantity and posts the
   movement and the cost layer, with `move_reference_type='adjustment'` and
   the call's UUID as the reference; the history row carries
   `mcp_correction`, the caller's reason text and that id;
3. the register's copy is written through
   `warehouse_api.record_count_differences_async`. It is `None` when Warehouse
   is off — the stock still moves and the answer says no document was kept.
   A correction that changes nothing writes no document;
4. `core_api.audit_log.log_action_async` adds the tool call to the
   organization journal. Its actor is the key's prefix, set where the request
   authenticated; the parameters are ids, numbers and the reason, never the
   key or anything secret.

The write tools need `items:write`; the read tools need `items:read` (and
`locations:read` where they name shelves). A key without `mcp_server:use`
cannot reach the endpoint at all.

A refused call answers `isError` with one text of the shape `CODE: sentence`,
the sentence in the request's language: a tool's own refusal
(`ITEM_NOT_FOUND`, `LOCATION_REQUIRED`, …), `PERMISSION_REQUIRED` naming the
permission the way the API key form does, and `ARGUMENT_REQUIRED` /
`ARGUMENT_INVALID` for arguments that break the published input schema —
each argument named with its type and its description from that schema, never
the value that was sent (`_http._InventariServer`).

## Checking the module

```bash
make validate-module
make module-smoke NAME=mcp_server
```

The tool catalogue is a contract:
`backend/app/modules/mcp_server/tests/integration/test_manifest_snapshot.py`
pins it, and a change to it carries a module version bump in `manifest.json`.
