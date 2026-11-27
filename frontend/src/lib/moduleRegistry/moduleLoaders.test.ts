import { describe, it, expect, vi } from "vitest";

import { moduleRegistry } from "./registry";
import { registerModules } from "./moduleLoaders";

/**
 * Registering is a per-module import, not an all-or-nothing side effect of the
 * entry chunk: every reader would otherwise download every `module.ts`,
 * including the ones their organization had
 * switched off. The loaders make it a per-module act, and these tests pin
 * the act itself.
 *
 * Nothing registers a module here but the loaders themselves, so what these
 * tests assert is what a call brings in: a module arrives when asked for and
 * stays out when it is not — and nothing is registered twice.
 */

const IMPORTED = "recipes";
const NOT_IMPORTED = "webhooks";
const BROKEN = "api_keys";

// A chunk that is gone after a deploy: the import itself rejects.
vi.mock("../../modules/api_keys/module.ts", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});

describe("registerModules", () => {
  it("imports the module it is given — a module it is not given stays out", async () => {
    await registerModules([IMPORTED]);

    expect(moduleRegistry.getModule(IMPORTED)).toBeDefined();
    expect(moduleRegistry.getModule(NOT_IMPORTED)).toBeUndefined();
  });

  it("skips names that ship no frontend module", async () => {
    // `core`, `items`, `storages` are enabled-list names without a
    // `module.ts` under src/modules/ — core surfaces, not modules.
    await expect(
      registerModules(["core", "items", "locations", IMPORTED]),
    ).resolves.toEqual([]);

    expect(moduleRegistry.getModule(IMPORTED)).toBeDefined();
  });

  it("registers once no matter how often it is called", async () => {
    await registerModules([IMPORTED]);
    const afterFirst = moduleRegistry.getAllRegisteredModules().length;

    await registerModules([IMPORTED]);

    expect(moduleRegistry.getAllRegisteredModules()).toHaveLength(afterFirst);
    expect(
      moduleRegistry.getAllRegisteredModules().filter((n) => n === IMPORTED),
    ).toHaveLength(1);
  });

  it("names the modules whose chunk did not load, and still registers the rest", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const failed = await registerModules([BROKEN, IMPORTED]);

    expect(errors).toHaveBeenCalled();
    expect(failed).toEqual([BROKEN]);
    expect(moduleRegistry.getModule(BROKEN)).toBeUndefined();
    expect(moduleRegistry.getModule(IMPORTED)).toBeDefined();
  });

  it("reports nothing failed when every chunk loads", async () => {
    await expect(registerModules([IMPORTED])).resolves.toEqual([]);
  });
});
