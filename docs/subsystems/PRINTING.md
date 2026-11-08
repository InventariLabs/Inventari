# Label & Printing System

## Short Codes
- `STM-XXXX`: Unique Items.
- Storage locations: a code that follows the location tree (`A-02-01`) in a
  business, or a random `LOC-XXXX` at home — `services/storage/_codes.py`.

## Architecture

The printing system is split into two tiers:

### Tier 1 — Server-side (always on)
- **Label Pool**: Pre-generated QR codes (`app.models.label_pool.LabelPool`).
- **Label Generator**: PNG generation service (`app.modules.printing.services.label_print_service`).
  A label of W × H mm is one file, W × H mm at 300 dpi, stating its resolution
  (`label_geometry.raster_for`). The download, the preview and a print job carry that same file;
  nothing about a printer changes how a label is drawn.
- **Export API**: `GET /api/v1/labels/pool/export/png` — returns a PNG batch of unprinted labels (or the ones named by `label_ids` / `short_codes`) and marks them as printed, unless `mark_printed=false`; with nothing unprinted it answers 400 `NO_LABELS_AVAILABLE`.
- **Print queue**: `app.modules.printing` — **Send to printer** in the app creates a print job for a
  registered agent; the agent claims it, fetches its image, prints it and reports the outcome. The
  labels count as printed only on a reported success.
- **Events**: `label.batch_generated` (after pool creation, and after labels are created from codes) and `label.batch_exported` (after PNG export).

### Tier 2 — Local (optional, print-agent)
Printer driver logic runs **outside the backend** as the [Inventari Print Agent](../../print-agent/README.md).
It always calls the server, never the other way round, so it needs no open port or tunnel:
- `serve` — registers the printer and asks the print queue for work every few seconds.
- `run` / `print-now` — prints the blank-label pool from the export API.
- `test-printer` — sends a test page to the printer.

Fitting the label file to a printer is the agent's job. A CUPS or command printer gets the 300 dpi
file as it is and its driver prints it at its stated size. A Brother P-touch has no driver: the
agent reads the tape's printable dots (`ptouch-print --info`), asks the server for the same label at
the printer's own raster (`dpi`, `max_height_px`), makes it 1-bit and prints it. A label taller than
the tape prints is scaled down as a whole; the agent reports the scale and the app shows it next to
the job.

```
[Inventari VPS]  ◄── HTTPS, agent-initiated ───  [Print Agent]  ───►  [Local Printer]
```

## Print Agent

See [`print-agent/README.md`](../../print-agent/README.md) for setup instructions.

Agent endpoints require `printing:agent`. An app session also needs
`org:settings:write`; a printing-scoped API key needs only its agent permission.
The app's side asks for the read of the screen that sends the label, by kind of label:

| Label | Sent from | Read |
|---|---|---|
| A product's barcode label (`item_ids`) | a product's card, the product list | `items:read` |
| A pool label (`label_ids`, `short_codes`) | Labels; the equipment register's asset list and its batch of new assets | `items:read` or `equipment:read` |
| A shelf (`location_ids`) | a location card; the warehouse's scan sheet and location codes | `locations:read` or `warehouse:read` |
| A dispatch's package | its package card, through the warehouse | `warehouse:read` |

The product label PNG and the demo sheet ask for `items:read`, the shelf label PNG for either shelf
read. The printers and the queue serve all of those screens, so any of their reads opens them. A job
keeps the reads of its kind (`read_permissions`; a label another module draws keeps the read that
module names): a new job is refused without one of them, and the job list and a retry show and
resend a job only to a holder of one. A community module's own screen sends pool labels and shelves
under the core reads; a label the module draws itself goes through `printing_api` under its own read.

| Env var | Description |
|---|---|
| `INVENTARI_URL` | Your Inventari instance URL |
| `INVENTARI_API_KEY` | API key (from Settings → API Keys; "Printing only" reaches nothing else and drives `serve`; the pool modes `run` and `print-now` need an ordinary key that can read products) |
| `PRINTER_TYPE` | `brother-p710bt`, `cups`, or `command` |
| `PRINTER_NAME` | CUPS printer name |
| `PRINTER_COMMAND` | Custom command template with `{file}` |
| `PRINTER_DPI` | The printer's resolution (default: 180 for a Brother, else the file's 300) |
| `PRINTER_MAX_HEIGHT_PX` | Dots the head prints across (a Brother reads it from its tape) |
| `SEPARATE_LABELS` | `serve`, Brother only: print a job's labels one by one, cut apart (default: true); `false` prints a job as one strip |
| `AGENT_NAME` | The printer's name in the app (default: host name) |
| `QUEUE_INTERVAL` | `serve`: seconds between asks for work (default: 3) |
| `POLL_INTERVAL`, `LABEL_*` | `run` / `print-now` only: poll interval, pool label size and batch |

## Print protocol

The queue's protocol is versioned: the agent's registration carries
`agent_version` (which build stands next to the printer) and `protocol_version`
(the protocol it speaks). The server records both on the agent — that is what
tells an old agent from a new one — logs them, and refuses a protocol outside
`PROTOCOL_MIN_VERSION`–`PROTOCOL_VERSION` (`app.modules.printing.schemas`)
with a reason the agent prints. An agent that names no protocol is refused
with it. The answer carries `server_protocol_version`, the protocol the server
speaks; an agent whose own differs says so and works as long as the server
still speaks its protocol.

Changing it: raise `PROTOCOL_VERSION` on both sides by one whenever a change
would break an agent already in the field — a request field renamed or
dropped, a meaning changed, an answer an agent reads differently. A change an
older agent simply ignores (a new optional field, a new field in an answer)
needs no bump. Keep `PROTOCOL_MIN_VERSION` where it is while those older
agents still work under the new code, and raise it only when they are gone:
the range is the server's promise about what runs in the field.

## An order with no total

A purchase order with a line that has no price has no total: the order's card,
its list and its approval rule all say so, and so does its printout. The default
layout prints the words the screens use (*No price yet*, in the language of the
document) for the net, tax and gross totals, a dash for that line's own amounts,
and no table of amounts per tax rate. What the priced lines add up to is not
printed, because it is not what the order is worth.

An organization's own template meets the same thing under `{{total_net}}`,
`{{total_tax}}` and `{{total_gross}}`:

| In the template | When a line has no price |
|---|---|
| `{{total_gross}}`, `{{total_gross\|format_decimal}}` | prints *No price yet* |
| `{{ row.net }}`, `{{ row.gross\|format_decimal }}` in `{% for row in lines %}` | prints `—` for that line |
| `{{ total_gross + 10 }}`, `{{ total_gross\|round(2) }}` | stays not known, and prints the same words |
| `{% if total_gross > 1000 %}`, `{% if total_gross <= 1000 %}` | is false: no comparison holds |
| `{% if total_gross %}` | is false, as it is for a total of zero |
| `{{ '%.2f'\|format(total_gross) }}` | prints `nan`: use `format_decimal`, which has the words |

No calculation or comparison on these values stops the print, so a template
tested only on a priced order still prints the unpriced one.
