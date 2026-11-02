# Example Widgets

## Job
"Show me, in code I can run and copy, how a module in this app is actually put together."

## Whose job
A developer writing their first module. No end user has any business here.

## Inside the boundary
The smallest complete module that still demonstrates every pattern that matters: its own table and
migration, a gated router, permissions with defaults, a frontend page, translations in all five
languages, and two contributions to another area's screens: a bulk action on the inventory list
(copying the selected IDs) and a validation rule on the new-item form (refusing a name made only
of digits, which is usually a mis-scan).

## Outside the boundary
Anything a workspace would actually use. The module is a worked example, not a feature.

## Own concepts / Borrowed
**Own:** Widget — a name, a colour, a quantity, whether it is active, and nothing else.
**Borrowed:** no data, on purpose. A reference module that leaned on another module's records would
teach the coupling along with the pattern; its two contributions reach inventory only through the
extension points the module SDK offers.

## Deliberately not done
- **No realistic domain.** A widget is deliberately meaningless so that nobody mistakes the example
  for a product, a part or an asset.
- **Never in a workspace mode.** No product profile installs it; it is switched on by a person who
  knows why.
- **No growth.** Every new pattern that lands here makes the example longer and the lesson smaller.
  It teaches the shape of a module, not the range of the platform.

## Switched off
This is its normal state. Everything else must be indifferent to it — if any other module or gate
notices that Example Widgets is missing, that is the defect.
