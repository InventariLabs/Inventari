import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * UI_GUIDELINES §2.2 / §4.3: a button's height and text size come from its
 * `size`, and a modal footer holds a compact pair aligned right rather than a
 * 50/50 split across the whole width on desktop.
 *
 * A source scan rather than a render: the four places checked here live in
 * components whose render needs a page's worth of context, and what is being
 * asserted is a property of the source, not of a rendered tree.
 */
const SRC = join(process.cwd(), "src");

function openingTags(source: string): string[] {
  const tags: string[] = [];
  for (const match of source.matchAll(/<Button\b/g)) {
    let i = match.index! + match[0].length;
    let depth = 0;
    let quote: string | null = null;
    while (i < source.length) {
      const char = source[i];
      if (quote) {
        if (char === quote) quote = null;
      } else if (char === '"' || char === "'") quote = char;
      else if (char === "{") depth++;
      else if (char === "}") depth--;
      else if (char === ">" && depth === 0) break;
      i++;
    }
    tags.push(source.slice(match.index!, i + 1));
  }
  return tags;
}

describe("resized buttons keep their size from the variant", () => {
  it.each([
    ["modules/shopping_lists/components/DashboardShoppingList.tsx", /go|list/i],
    ["modules/settings/components/OrganizationSettings.tsx", /invite/i],
  ])("%s has no full-width button on a wide surface", (relative) => {
    const source = readFileSync(join(SRC, relative), "utf8");
    for (const tag of openingTags(source)) {
      const className = tag.match(/className="([^"]*)"/)?.[1] ?? "";
      // `w-full` belongs on narrow surfaces (a max-w card, a mobile sheet) or
      // on a button standing in for a list row — neither is the case here.
      expect(className.split(/\s+/)).not.toContain("w-full");
      expect(className.split(/\s+/)).not.toContain("h-14");
    }
  });

  it("the label preview footer is a compact pair, not a 1:2 split", () => {
    const source = readFileSync(
      join(SRC, "modules/inventory/components/labels/LabelPreviewModal.tsx"),
      "utf8",
    );
    for (const tag of openingTags(source)) {
      const className = tag.match(/className="([^"]*)"/)?.[1] ?? "";
      if (!className.includes("w-full")) continue;
      expect(className).toContain("sm:w-auto");
      expect(className).not.toMatch(/sm:flex-/);
      expect(className.split(/\s+/)).not.toContain("py-4");
    }
  });

  it("the join screen's button takes its colour from a variant", () => {
    // It was `bg-gray-900 text-white hover:bg-black` — a raw palette that does
    // not follow the theme, on a button that also built its own height.
    const source = readFileSync(
      join(SRC, "modules/settings/pages/JoinOrganizationPage.tsx"),
      "utf8",
    );
    for (const tag of openingTags(source)) {
      const className = tag.match(/className="([^"]*)"/)?.[1] ?? "";
      expect(className).not.toMatch(/\bbg-gray-\d00\b/);
      expect(className.split(/\s+/)).not.toContain("h-auto");
    }
  });
});
