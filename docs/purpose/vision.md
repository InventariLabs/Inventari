# Photo Recognition

## Job
"Point the camera at the packet and let it fill in the name, the brand and the date, so I do not
have to type them off a label in bad light."

## Whose job
Whoever adds products, usually on a phone, usually with the product in the other hand.

## Inside the boundary
Sending an image to whichever AI connection is bound to this purpose and turning the answer into
values a product form can accept: name, brand, barcode, the printed dates, net weight or volume, a
category, and the fields other modules ask to have read (the nutrition table). A field is either
read or left empty; nothing is scored for how sure it is.

Several photographs of one item are read together. A barcode the reading finds goes through the same
resolvers as a scanned code, and a product it matches comes back with the reading. The module has no
screens of its own: the photo tab sits in the add-product flow, and the nutrition-table scanner in
nutrition. Requests are limited to twenty a minute.

## Outside the boundary
- Which model answers, and with what key → **Core — Settings** (AI connections and purpose bindings)
- What the fields mean and where the product ends up → **Core — Inventory**
- Nutritional values from a public database → **nutrition**

## Own concepts / Borrowed
**Own:** the extraction request, its output contract, and the field groups other modules contribute
to it.
**Borrowed:** the LLM subsystem; the product fields it fills.

## Deliberately not done
- **No model of its own.** Nothing is trained or tuned, and the module runs no model itself; a
  model on the operator's own machine is just another AI connection.
- **No saving without a person.** The result is a filled-in form somebody confirms, never a record
  written on the strength of a photograph.
- **No inference past the label, but one suggestion.** It reads what is printed and does not guess
  a price or a shelf life. The category is the exception: the model picks one from a fixed list of
  food categories, and the form takes it only when it matches one of the workspace's own —
  otherwise it is shown as a hint, not filled in.
- **No image library.** Photographs are a means of reading, not an archive.

## Switched off
Adding a product falls back to typing, and it must do so without a dead camera button or a screen
that has lost a step. A failure of the provider is not the same as the module being off, and the two
must not look alike to the user.
