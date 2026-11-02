# Inventari Print Agent

A lightweight local daemon that bridges your Inventari instance with a
physical label printer. Its main mode, **serve**, prints the labels you send
to this printer from the app; **run** prints the pool of blank labels as it
fills.

## Why a separate agent?

Inventari runs on a VPS — it has no access to USB printers or local CUPS
queues. The agent runs on your local machine (or a Raspberry Pi next to
the printer) and uses the Inventari API to fetch labels as PNG, then
sends them to whatever printer you have configured. It always calls the
server, never the other way round, so it works behind a home router with no
port opened and no tunnel.

## Quick start

Requires Python 3.11 or newer (Pillow 13); the agent refuses to start on an
older interpreter and says what it needs.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set INVENTARI_URL, INVENTARI_API_KEY, PRINTER_TYPE, AGENT_NAME

# 3. Test printer
python agent.py test-printer

# 4. Print what the app sends to this printer
python agent.py serve
```

## API Key

Generate an API key in Inventari → **Settings → API Keys** and choose
**Printing only** under "What the key is for". Such a key reaches the print
agent's endpoints and nothing else: it cannot read the inventory or change
anything, which matters for a key that lives on a machine in the garage. An
ordinary key works too when it carries the "Act as a print agent" permission,
but reaches whatever else its permissions allow. The blank-label pool modes
(`run`, `print-now`) read the pool through the ordinary label export, which
a printing-only key is refused (`API_KEY_SCOPE_REFUSED`): those two modes need
an ordinary key that can read items.

The agent sends the key in the `X-API-Key` header, and also as
`Authorization: Bearer <key>` for servers from before keys had a header of
their own; a newer server reads `X-API-Key` and ignores the copy.

## Operating modes

### Print queue (`serve`)

```bash
python agent.py serve        # asks for work every QUEUE_INTERVAL seconds (default: 3)
```

On start the agent registers this printer under `AGENT_NAME` (default: the
host name) and its printer type, and says which print protocol it speaks and
which release of the agent this is. The server records both, refuses a
protocol it does not speak — its reason is printed in the agent's log — and
answers with the protocol it speaks, so a gap the two still work across is
only a warning here. The protocol and the rule for changing it are in
[docs/subsystems/PRINTING.md](../docs/subsystems/PRINTING.md). From then on,
every label download in the app — the label pool, a storage location, a
product's barcode label, equipment — shows **Send to printer** beside it. The agent claims the job,
fetches the labels' image, fits it to this printer (see [Your printer](#your-printer)),
prints it and reports how it went:

- the labels count as printed only when the agent reports success;
- a printer failure is reported with its reason, the labels stay unprinted and
  the job can be sent again from the app (Labels → Printers and print jobs);
- an agent that dies mid-job reports nothing; its claim expires after two
  minutes and the job is handed out again. The report names the claim it
  answers, so an agent that stalls past its lease and wakes up later cannot
  close the job under the claim printing it now;
- a job that printed and whose report never reached the server is
  remembered: when its claim expires and the job comes back, the agent
  reports it printed instead of printing it again. Only an agent restarted
  in between prints it twice — the queue prints at least once, not exactly
  once, and a spare strip of tape is the price of never losing a label.

The label's size is chosen in the app, in the label preview: the job
carries it, and the image the agent gets is the same label the preview shows
and the download gives. Nothing about a printer is set in the app.

### Blank-label pool (`run`, `print-now`)

```bash
python agent.py run          # polls every POLL_INTERVAL seconds (default: 30)
python agent.py print-now    # one-shot
```

Prints the pool's unprinted, unassigned labels — stickers to put on boxes
before anything is assigned to them, at `LABEL_WIDTH` × `LABEL_HEIGHT` mm
(default 50 × 24), at most `LABEL_BATCH_SIZE` (default 50) per cycle.
`LABEL_COLUMNS` (labels per row; default: all in one strip) and
`LABEL_QR_ONLY=true` (no caption) shape the sheet. The export marks the labels
printed when the image is downloaded, so a printer failure in this mode loses
the batch.

## Your printer

Inventari draws one label file for every printer: a label of W × H mm is a
PNG of W × H mm at 300 dpi, and the file says so in its header. Fitting that
file to a printer happens here, next to the printer.

| `PRINTER_TYPE` | What it does |
|---|---|
| `brother-p710bt` | Runs `ptouch-print --image {file}` (requires [ptouch-print](https://dominic.familie-radermacher.ch/projekte/linux/ptouch-print/)) |
| `cups` | Runs `lpr -P {PRINTER_NAME} {file}` (`lpr {file}`, the system default printer, when `PRINTER_NAME` is blank) |
| `command` | Runs your custom `PRINTER_COMMAND` template |

### A printer with a driver (CUPS)

An office printer, or a label printer with a CUPS driver, prints the file as
it comes: the PNG states its resolution, so the driver prints a 50 × 24 label
at 50 × 24 mm. Set the label size in the printer's queue to the size of your
labels, and choose the same size in the label preview in the app.

```bash
PRINTER_TYPE=cups
PRINTER_NAME=office-label-printer
```

The `command` type runs any command that takes a file, for options of your
own:

```bash
PRINTER_TYPE=command
PRINTER_COMMAND=lp -d zebra -o media=Custom.50x24mm {file}
```

A thermal label printer is usually 203 or 300 dpi. Tell the agent its
resolution and it asks Inventari for the label drawn at it, so the QR code's
modules land on whole dots instead of being resampled by the driver; tell it
how many dots the head prints across and a taller label is scaled down to
fit:

```bash
PRINTER_DPI=203
PRINTER_MAX_HEIGHT_PX=384
```

### A Brother P-touch

A P-touch has no driver here: `ptouch-print` takes a black-and-white PNG no
taller than the tape's printable dots and prints it as it is. The agent does
the fitting:

- before every job it asks the printer what tape it holds (`ptouch-print
  --info`): a 24 mm cassette prints 128 dots, about 18 mm, a 12 mm one 64;
- it asks Inventari for the label drawn at 180 dpi (`PRINTER_DPI` to change
  it) within those dots, and makes it black and white;
- a label taller than the tape prints is scaled down as a whole. A 50 × 24
  label on 24 mm tape prints at 75 %, about 38 × 18 mm, and the job says so
  in the app (Labels → Printers and print jobs). For a label at its size,
  make it as tall as the tape prints: 18 mm on 24 mm tape, 9 mm on 12 mm;
- a QR-only label (no caption, no short code) fills the tape: the tape's
  unprinted edges are the white border a scanner needs, so the code takes all
  the dots across it and keeps its white border only along the tape. On 24 mm
  tape a typical scan link prints at 4 dots a module, about 16 mm, where a
  paper label's layout would leave it 12 mm. A code beside a caption, with no
  short code under it, does the same while the caption keeps its size; a
  caption too long for the room left keeps the width it needs, and the code
  stays smaller;
- a printer that is off or not found fails the job with what `ptouch-print`
  said, and the labels stay unprinted.

The P-touch's cutter sits about 25 mm ahead of its head, so every separate
print starts with that much blank tape. It is the printer's, not the label's,
and the preview does not show it.

**A job of several labels comes out cut apart.** The agent prints it label by
label: it asks Inventari for each label alone (the job's image with
`index=0`, `1`, …), gives every label but the last `--chain` (no final feed and
cut) and every label but the first `--precut` (cut before the label), so the
blank lead is paid once per job rather than once per label. The labels count
as printed only when every one printed; a failure names the label it stopped
at (`Label 2 of 3: …`), and the ones before it are already on the tape. The
tape of a job that stopped halfway is not cut: feed and cut it by hand before
the next job.

The price is a little more tape between labels than one continuous strip
would use, and one `ptouch-print` call per label. To print a job as a single
strip again, which you cut apart yourself, set `SEPARATE_LABELS=false`
(in `.env` or the environment); a job of one label is printed the same way
either way. Other printer types always get the strip.

## Running as a systemd service

```ini
# /etc/systemd/system/inventari-print-agent.service
[Unit]
Description=Inventari Print Agent
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/inventari-print-agent
EnvironmentFile=/opt/inventari-print-agent/.env
ExecStart=/usr/bin/python3 agent.py serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now inventari-print-agent
```

## Tests

```bash
cd print-agent
uv run --with-requirements requirements.txt --with pytest pytest tests
```

The Inventari API is stubbed and the printer is a shell command that copies
the PNG, so the tests need neither a server nor a printer.

## Licence

AGPL-3.0-only, as Inventari itself — see [LICENSE](LICENSE). This directory
carries its own copy because the agent is the piece installed on machines
away from the server.
