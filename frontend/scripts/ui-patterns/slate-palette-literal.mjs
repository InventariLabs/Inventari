import { paletteFindings } from "./success-palette-literal.mjs";

/**
 * A raw `slate-*` class where the `gray-*` scale exists.
 *
 * The product's neutral is the zinc-based `gray-*` ramp; a `slate-*` literal
 * is a cooler grey that sits next to it and matches nothing in dark mode
 * (UI_GUIDELINES §1.1). A swatch the user picks for their own item or widget
 * is identity, not neutral chrome, and takes the same escape hatch as
 * `success-palette-literal`:
 *
 *   {\/* ui-pattern: palette-identity — the swatch shows the colour the user
 *       chose, not a neutral surface *\/}
 */
const SLATE_LITERAL =
  /\b(?:bg|text|border|ring|divide|from|via|to|fill|stroke|decoration|caret|shadow|outline)-slate-(?:50|[1-9]00)\b/g;

export default {
  name: "slate-palette-literal",
  corpus: "scripts",
  says:
    "A raw slate-* class is a second grey beside the product's gray-* " +
    "scale — it matches no token and neither profile nor dark mode repaints " +
    "it (UI_GUIDELINES §1.1).",
  advice:
    "Swap the literal for the gray-* scale (bg-gray-100, text-gray-700, …). If\n" +
    "the colour is one the user picked as an identity, say so at the call site:\n" +
    "ui-pattern: palette-identity — <why the token would be wrong here>.",

  run(files) {
    return paletteFindings(files, SLATE_LITERAL);
  },
};
