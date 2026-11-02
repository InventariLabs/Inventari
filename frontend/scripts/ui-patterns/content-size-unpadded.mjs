import {
  classNameAlternatives,
  classNameOf,
  lineAt,
  openingTags,
  sizeOf,
  withoutResponsive,
} from "./lib.mjs";

/**
 * The sizes that hand the height back to the call site.
 *
 * `content` and `contentSm` are `default` and `sm` with `h-auto` — they exist
 * so a row can be as tall as what it holds. The catch is that they also drop
 * the vertical padding, so a button holding one line of text renders at the
 * line's own height: 21px, against a 44px touch floor.
 */
const UNSIZED = new Set(["content", "contentSm"]);

/**
 * `auto` is deliberately not a value: `h-auto` is what `content` already is,
 * so stating it says nothing the size had not said, and the button stays as
 * tall as its text.
 */
const VALUE = "(?:full|screen|fit|min|max|\\d+(?:\\.5)?|\\[[^\\]]+\\])";
const HEIGHT = new RegExp(`(?:^|[\\s"'\`{])(?:min-h|h|py|p)-${VALUE}`);

export default {
  name: "content-size-unpadded",
  says:
    'A <Button size="content"> that states no vertical padding, height or ' +
    "min-height is as tall as its own text — 21px for one line, half the " +
    "height of the controls beside it and well under the 44px touch floor " +
    "UI_GUIDELINES §2.10 asks for.",
  advice:
    "State the rhythm at the call site — `py-2 min-h-11 md:min-h-10` for a\n" +
    "row of text — or ask for a size that carries its own height. This is\n" +
    "the mirror image of `button-size-override`: there the call site says a\n" +
    "dimension the variant already pins, here the variant pins none and the\n" +
    "call site says nothing either.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      for (const { tag, index } of openingTags(file.text, "Button")) {
        if (!UNSIZED.has(sizeOf(tag))) continue;

        considered.add(file.path);

        // Each branch is asked separately: a ternary whose other half is
        // padded reads as padded when the expression is taken whole, and the
        // bare branch is the one that renders a 21px row.
        //
        // Responsive spellings are stripped for the same reason
        // `button-size-override` strips them: a rule about what happens below
        // `md` must read what applies below `md`.
        const bare = classNameAlternatives(classNameOf(tag)).some(
          (alternative) => !HEIGHT.test(withoutResponsive(alternative)),
        );
        if (bare) findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
