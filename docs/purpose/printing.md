# Label Printing

## Job
"Get a label onto the box or the shelf, so that scanning it later finds exactly this thing."

## Whose job
Whoever puts things away prints labels. Whoever runs the installation sets up the printer once,
outside the app.

## Inside the boundary
What goes on a label and how it is laid out — the QR code, the short code printed beside it, and the
caption (typed by the person printing, or for a product its name and expiry) — the generated image at the size the media actually is, and the pool of pre-generated codes waiting to be
assigned. And the print queue: the printers the organization's print agents have announced, the
labels sent to each of them, and whether they printed. A pool label counts as printed when the
agent says so, or when its image is exported to be printed by hand; a preview of the image does not
spend it.

## Outside the boundary
- The printer itself and its driver → the Inventari Print Agent, on the local machine, which asks
  the queue for work rather than being called — it lives behind somebody's router
- What a scanned code resolves to → **Core — Inventory**, **Core — Spaces**
- Reading a code with a camera → the scanner in the app shell

## Own concepts / Borrowed
**Own:** label layout and its geometry, the short code as printed, PrintAgent, PrintJob, the
`printing:agent` permission the agent's endpoints guard, and the `printing` API key scope bound to it
(a key that reaches the agent's endpoints and nothing else).
**Borrowed:** the label pool (LabelPool, a Core record served by the Core label routes); Item,
ProductTemplate (Inventory); StorageLocation and its short code (Spaces).

## Deliberately not done
- **No printer drivers in the backend.** The server produces an image; something local prints it.
  This is why label geometry is expressed in millimetres and not in one printer's dots.
- **No free-form design canvas.** A label is a defined layout with options, not a drawing surface —
  a code that scans is worth more than a label that is pretty.
- **No stock of label media.** How many stickers are left on the roll is not modelled.

## Switched off
Cannot be. Labelling is part of the box: a printed sticker points at a scan address that has to
resolve in every workspace, whatever its mode. Without a print agent nothing is lost but the queue —
labels are exported as an image and printed by hand.
