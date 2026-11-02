import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * `module validate` and `module install` warn about a manifest icon this
 * component cannot draw. They decide from `MANIFEST_ICONS` in
 * backend/app/core/manifest_icons.py, so that list must be exactly the keys
 * of `ICON_MAP` — a name on only one side is either a false warning or a
 * silent fallback to the package icon.
 */
const HERE = dirname(fileURLToPath(import.meta.url));
// `<src>/../..` — the repo root on the host, `/` in the frontend container.
const BACKEND_LIST = resolve(
  HERE,
  "../../../../backend/app/core/manifest_icons.py",
);

function frontendKeys(): Set<string> {
  const source = readFileSync(resolve(HERE, "DynamicIcon.tsx"), "utf8");
  const body = source
    .split("const ICON_MAP: Record<string, LucideIcon> = {")[1]
    .split("};")[0];
  return new Set(
    [...body.matchAll(/^\s*(\w+)\s*[,:]/gm)].map((match) => match[1]),
  );
}

function backendNames(): Set<string> {
  const source = readFileSync(BACKEND_LIST, "utf8");
  const body = source.split("MANIFEST_ICONS = frozenset(")[1].split("\n)")[0];
  return new Set([...body.matchAll(/'(\w+)'/g)].map((match) => match[1]));
}

describe("manifest icon list", () => {
  it("is exactly the icons DynamicIcon can draw", () => {
    expect([...backendNames()].sort()).toEqual([...frontendKeys()].sort());
  });
});
