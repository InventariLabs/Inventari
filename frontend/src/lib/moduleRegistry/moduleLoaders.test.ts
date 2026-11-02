import { describe, it, expect } from "vitest";

import { moduleRegistry } from "./registry";
import { registerModules } from "./moduleLoaders";

/**
 * Registering used to be an all-or-nothing side effect of the entry chunk:
 * `App` globbed every `module.ts` with `eager: true`, so every reader
 * downloaded all of them — including the ones their organization had
 * switched off. The loaders make it a per-module act, and these tests pin
 * the act itself.
 *
 * The shared test setup (`src/test/setup.ts`) imports a handful of modules
 * for every test file, so the registry never starts empty here. What these
 * tests assert is the delta: a module the setup does not touch arrives when
 * asked for and stays out when it is not — and nothing is registered twice.
 */

// Neither name is among the setup file's imports, and no setup module
// transitively imports their `module.ts`.
const IMPORTED = "recipes";
const NOT_IMPORTED = "webhooks";

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
    ).resolves.toBeUndefined();

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
});
