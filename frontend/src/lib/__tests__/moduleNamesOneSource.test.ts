import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A module's user-visible name has one source: `modules.<name>.name` in the
 * `modules` namespace, resolved through `useModuleLabels`
 * (docs/MODULE_NAMES.md, frontend/AGENTS.md §4, "Module display names"). The manifest's
 * `display_name` is a fallback for a community module this build has never
 * heard of — not something a screen renders on its own.
 *
 * Three screens broke that rule at once: the profile-switch diff printed
 * `display_name` straight from the manifest (`Approvals`, `Purchase Orders`
 * — English in a Polish interface) and the raw identifier for shell modules
 * (`categories`, `core`), while the 404 screen capitalised the identifier and
 * produced "Example_widgets", underscore included.
 *
 * This scan is the gate the next one hits before review does.
 */

const SRC = join(process.cwd(), "src");

/** Where reading `display_name` is the honest answer. */
const ALLOWED = [
  // The resolver itself — this is the fallback it documents.
  "hooks/useModuleLabels.ts",
  // The store's search matches the technical and the manifest name on purpose
  // so an admin can find a module by either.
  "modules/settings/components/AppStore.tsx",
];

/** `{mod.display_name}` or `{module.display_name}` rendered into JSX. */
const RENDERED_DISPLAY_NAME = /\{\s*[\w.?]*\.display_name\s*\}/;

/**
 * Capitalising a module identifier is naming a module by hand — that is where
 * "Example_widgets" came from. Deliberately narrow: PascalCasing an icon name
 * or building an i18n key out of a filter value is not naming a module.
 */
const CAPITALISED_IDENTIFIER =
  /\b\w*[Mm]odule\w*\.charAt\(0\)\.toUpperCase\(\)/;

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      out.push(...walk(full));
      continue;
    }
    if (!/\.tsx?$/.test(entry) || /\.test\.tsx?$/.test(entry)) continue;
    out.push(full);
  }
  return out;
}

interface Finding {
  where: string;
  line: string;
}

function scan(pattern: RegExp): Finding[] {
  const findings: Finding[] = [];
  for (const file of walk(SRC)) {
    const rel = relative(join(process.cwd(), "src"), file);
    if (ALLOWED.some((allowed) => rel === allowed)) continue;
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, index) => {
        if (pattern.test(line)) {
          findings.push({
            where: `src/${rel}:${index + 1}`,
            line: line.trim(),
          });
        }
      });
  }
  return findings;
}

describe("a module is named in one place", () => {
  it("finds files to scan (the gate is not vacuous)", () => {
    expect(walk(SRC).length).toBeGreaterThan(100);
  });

  it("has no screen rendering a manifest display_name", () => {
    expect(scan(RENDERED_DISPLAY_NAME).map((f) => f.where)).toEqual([]);
  });

  it("has no screen capitalising an identifier into a name", () => {
    expect(scan(CAPITALISED_IDENTIFIER).map((f) => f.where)).toEqual([]);
  });
});
