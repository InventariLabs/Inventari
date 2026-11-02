import { describe, it, expect } from "vitest";

import { MODULE_PATHS } from "./modulePaths";
import { moduleRegistry } from "./registry";

// Every module registers itself on import; the table exists so that a reader
// who has NOT imported them (NotFoundPage, an organization with the module
// switched off) can still tell which module owns a path.
const loaders = import.meta.glob<unknown>("../../modules/*/module.ts", {
  eager: true,
});

describe("MODULE_PATHS", () => {
  it("agrees with every module's own routes", () => {
    void loaders;

    const names = moduleRegistry.getAllRegisteredModules();
    expect(names.length).toBeGreaterThan(0);

    for (const name of names) {
      const mod = moduleRegistry.getModule(name);
      expect(mod, name).toBeDefined();
      const real = {
        basePath: mod?.moduleNav?.basePath ?? null,
        paths: (mod?.routes ?? []).map((route) => route.path),
      };
      // A module that owns no path is absent from the table; the comparison
      // reads that absence as "no paths", so a module that gains its first
      // route fails here until the table says so.
      const table = MODULE_PATHS[name] ?? { basePath: null, paths: [] };
      expect({ name, ...table }).toEqual({ name, ...real });
    }

    for (const name of Object.keys(MODULE_PATHS)) {
      expect(names, `${name} is in the table but is not a module`).toContain(
        name,
      );
    }
  });
});
