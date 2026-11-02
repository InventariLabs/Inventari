import {
  classNameOf,
  lineAt,
  openingTags,
  sizeOf,
  withoutResponsive,
} from "./lib.mjs";

/**
 * Which dimension each `size` pins with a responsive modifier.
 *
 * `cn()` is `twMerge`, and twMerge resolves conflicts inside a variant group:
 * a plain `h-8` displaces the variant's `h-11` and leaves its `md:h-10`
 * standing. So the override wins below `md` and loses on every desktop —
 * silently, which is why review keeps passing it. Sizes free of responsive
 * modifiers (`lg`, `iconSm`, `inline`) can be overridden safely and are absent
 * from this table on purpose.
 */
const PINNED = {
  default: ["h"],
  md: ["h"],
  sm: ["h"],
  icon: ["h", "w"],
};

const VALUE = "(?:auto|full|screen|fit|min|max|\\d+(?:\\.5)?|\\[[^\\]]+\\])";

function pinnedDimensionIn(className, dimensions) {
  const plain = withoutResponsive(className);

  return dimensions.some((dim) => {
    const pattern = `(?:min-|max-)?(?:${dim}|size)-${VALUE}`;
    if (!new RegExp(`(?:^|[\\s"'\`{])${pattern}`).test(plain)) return false;

    // A call site that answers the variant at its own breakpoint has closed
    // the gap deliberately — `h-auto md:h-auto` displaces `md:h-10` and holds
    // at every width. Flagging that would leave the fix with nowhere to go.
    return !new RegExp(`\\bmd:${pattern}`).test(className);
  });
}

/**
 * The scan both this detector and the narrower `icon-button-size` gate run,
 * so the blocking rule can never disagree with the report about what the
 * class *is* — only about how much of it is enforced today.
 */
export function scan(files, sizes = Object.keys(PINNED)) {
  const considered = new Set();
  const findings = [];

  for (const file of files) {
    for (const { tag, index } of openingTags(file.text, "Button")) {
      const size = sizeOf(tag);
      if (!sizes.includes(size)) continue;

      const className = classNameOf(tag);
      if (!className) continue;

      considered.add(file.path);
      if (pinnedDimensionIn(className, PINNED[size]))
        findings.push(`${file.path}:${lineAt(file.text, index)}`);
    }
  }

  return { considered: considered.size, findings };
}

export default {
  name: "button-size-override",
  says:
    "A dimension class in a <Button> className fights a `size` variant that " +
    "pins that dimension responsively — the class applies below `md` and is " +
    "dropped above it, so the button is one size on a phone and another on " +
    "every desktop, with nothing in the code to show it.",
  advice:
    'Ask for the size instead: size="iconSm" (32px), size="lg", or\n' +
    'size="inline" (intrinsic). If no size fits, add one to Button.tsx\n' +
    "without responsive modifiers, the way `iconSm` is written — a size\n" +
    "below the touch floor is a variant, not an override.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      for (const { tag, index } of openingTags(file.text, "Button")) {
        const dimensions = PINNED[sizeOf(tag)];
        if (!dimensions) continue;

        const className = classNameOf(tag);
        if (!className) continue;

        considered.add(file.path);
        if (pinnedDimensionIn(className, dimensions))
          findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
