import { describe, it, expect } from "vitest";

import { moduleRegistry } from "../moduleRegistry";

/**
 * The nav-override coverage gate: a module may hide a core navigation entry
 * only when its own screens cover the whole dataset that entry led to. An
 * override whose screen lists a subset strands the rest of the dataset —
 * with Equipment enabled, the organization's plain storage locations and
 * categories had no door left in the navigation except a link inside the
 * product form or a typed address.
 *
 * Equipment's Locations screen lists only the module scope and its
 * Categories screen filters on the module's context tag, so the hiding
 * overrides it once declared are gone and the honest allowance is empty.
 * Re-adding one strands the organization's locations again — this gate
 * goes red until the module's own screen actually covers the dataset.
 */

// Registering every real module, the same way App.tsx does.
import.meta.glob("../../modules/*/module.ts", { eager: true });

// Paths a module is allowed to hide from the core navigation, each with the
// module that hides it and the dataset its own screens cover. Empty today:
// the one hiding pair in the tree covered a subset, not the dataset.
const ALLOWED_TO_HIDE: { module: string; path: string; covers: string }[] = [];

describe("nav override coverage gate", () => {
  const hiding = moduleRegistry
    .getAllRegisteredModules()
    .map((name) => ({ name, mod: moduleRegistry.getModule(name)! }))
    .flatMap(({ name, mod }) =>
      (mod.navOverrides ?? [])
        .filter((o) => o.hidden)
        .map((o) => ({ module: name, path: o.targetPath })),
    );

  it("no module hides a core nav entry without covering its dataset", () => {
    const unallowed = hiding.filter(
      (h) =>
        !ALLOWED_TO_HIDE.some(
          (a) => a.module === h.module && a.path === h.path,
        ),
    );
    expect(unallowed).toEqual([]);
  });

  it("names no stale allowance — the list only carries live declarations", () => {
    for (const a of ALLOWED_TO_HIDE) {
      expect(
        hiding.some((h) => h.module === a.module && h.path === a.path),
      ).toBe(true);
    }
  });
});
