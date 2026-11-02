# Nutrition Info

## Job
"Show me what is actually in this product, without typing it off the packet."

## Whose job
Anyone looking at a product. Nobody visits this module directly — it appears inside the product it
describes.

## Inside the boundary
Getting a product's nutrition three ways — looking it up by its barcode in the copy of the Open Food
Facts database the installation holds (loaded from a Parquet dump with `make off-import`; nothing
calls Open Food Facts live), reading the table off a photographed packet, or typing it in — and
presenting it: values per 100 g or
100 ml, the ingredient list, and the Nutri-Score grade and nutrient levels when Open Food Facts
supplies them.

## Outside the boundary
- The photograph reading itself — the model and its provider → **vision**; this module only names
  the fields it wants read
- What a dish made from these products contains → **recipes**
- The product record itself → **Core — Inventory**

## Own concepts / Borrowed
**Own:** the imported nutrition record and its provenance.
**Borrowed:** ProductTemplate and its barcode (Inventory).

## Deliberately not done
- **No scoring of its own.** The Nutri-Score and the low/moderate/high levels are shown as Open Food
  Facts gives them; nothing here computes a grade, warns about allergens or says whether something
  is healthy.
- **No editing upstream.** Nothing this workspace does is sent back to Open Food Facts.
- **No made-up values.** A product not in the database shows nothing, not an estimate.
- **No lookup of in-store codes.** GS1 restricted-circulation numbers, which each shop prints for its
  own shelves, are never looked up: the same digits name a different product in every shop.

## Switched off
Products lose a section; nothing else changes. A recipe's own summary must not silently start
reporting different numbers because the source disappeared.
