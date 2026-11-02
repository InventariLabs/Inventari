import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeAll } from "vitest";
import { moduleRegistry } from "./moduleRegistry";

/**
 * A module that exposes settings must offer a way in from its own nav bar
 * (UI_GUIDELINES §2.14a). Otherwise the only entrance is
 * /settings/modules/<name>, which is reached from the App Store and leads back
 * out to it — the user leaves the module to change how the module behaves.
 *
 * The list is not maintained here by hand, and it is no longer read out of
 * Python either. `has_settings_schema` in each module's manifest.json is the
 * declaration, test_manifest_settings_schema.py holds it to what
 * `BaseModule.get_settings_schema` actually does, and
 * scripts/check-module-settings.mjs carries it into the snapshot read below —
 * the frontend container mounts ./frontend and cannot see the backend at all.
 *
 * The previous version globbed the backend's module.py files as raw text and
 * matched a regex against them. Wherever that tree was absent the glob
 * returned nothing and every assertion here passed by describing an empty
 * world; and the regex was only accidentally right, since `approvals` attaches
 * its schema by assignment rather than by defining a method.
 *
 * `webhooks` deliberately stays in the global settings: it is an integration,
 * not a module surface. `approvals` configures itself through its own screens.
 * `stats` has no bar of its own to put the entry in — its screens live inside
 * the inventory module's shell (`/inventory/stats` is an inventory nav item),
 * and the one toggle it declares (`enable_analytics`) is an admin-facing
 * module setting, flipped from Settings → Modules → stats. `stock_takes` is
 * the same case: its screens are inventory nav items too, and its one setting
 * (`count_every_days`) is how often the whole organization counts, set once
 * by an admin; the stock-take list links an admin to it, as approvals does.
 */
const MODULES_WITH_SETTINGS_SCHEMA: string[] = JSON.parse(
  readFileSync(join(process.cwd(), "scripts", "module-settings.json"), "utf8"),
);

const GLOBAL_SETTINGS_EXCEPTIONS = new Set([
  "webhooks",
  "approvals",
  "stats",
  "stock_takes",
]);

const MODULES_REQUIRING_OWN_SETTINGS = MODULES_WITH_SETTINGS_SCHEMA.filter(
  (name) => !GLOBAL_SETTINGS_EXCEPTIONS.has(name),
);

// Load only the modules under test (lazy glob — the eager app-wide import in
// App.tsx stays out of the test's way).
const moduleLoaders = import.meta.glob("../modules/*/module.ts");

describe("module settings are reachable from inside the module", () => {
  beforeAll(async () => {
    for (const name of MODULES_REQUIRING_OWN_SETTINGS) {
      const loader = moduleLoaders[`../modules/${name}/module.ts`];
      if (!loader)
        throw new Error(
          `${name} has a backend settings schema but no frontend module`,
        );
      await loader();
    }
  });

  it("the backend scan actually finds schemas (the gate is not vacuous)", () => {
    // `recipes` is the canonical case; an empty scan would make every
    // assertion below silently pass.
    expect(MODULES_WITH_SETTINGS_SCHEMA).toContain("recipes");
    expect(MODULES_REQUIRING_OWN_SETTINGS.length).toBeGreaterThan(0);
  });

  it.each(MODULES_REQUIRING_OWN_SETTINGS)(
    "%s has a settings entry last in its module bar",
    (name) => {
      const mod = moduleRegistry.getModule(name);
      expect(mod, `${name} is not registered`).toBeDefined();

      const items = mod!.moduleNav?.items ?? [];
      const settingsEntry = items.find((i) => i.order === 90);
      expect(settingsEntry, `${name} has no order:90 nav entry`).toBeDefined();

      // It must lead into the module, not to the global settings shell.
      expect(settingsEntry!.path).toContain(mod!.moduleNav!.basePath);
      expect(settingsEntry!.path).not.toContain("/settings/modules");

      // And that path must actually resolve to a route of this module.
      const paths = mod!.routes.map((r) => r.path);
      expect(paths).toContain(settingsEntry!.path);
    },
  );

  it("keeps the settings entry the last one in the bar", () => {
    for (const name of MODULES_REQUIRING_OWN_SETTINGS) {
      const items = moduleRegistry.getModule(name)!.moduleNav!.items;
      const maxOrder = Math.max(...items.map((i) => i.order ?? 0));
      expect(maxOrder, `${name}`).toBe(90);
    }
  });
});
