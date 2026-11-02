import { afterEach, describe, expect, it } from "vitest";
import i18n from "i18next";

import type { FrontendModule } from "./moduleInterfaces";
import { moduleRegistry } from "./registry";

/**
 * The label a sidebar renders must not depend on the order in which the
 * language chunks happen to land: one module renames core vocabulary for the
 * whole organization, the catalog carries the base names, and both write into
 * the same namespace with overwrite on. Whoever writes last used to win, so
 * the same screen flipped between "Products" and "Assets" across reloads.
 *
 * The catalogs used to arrive with `moduleRegistry.register`. They arrive
 * through the dynamic i18n backend now (`src/i18n/config.ts`), which
 * announces each one after i18next has merged it; the registry subscribes
 * (`onCatalogLoaded`) and calls `catalogLoaded`. The tests drive that call
 * directly — the subscription wiring itself is what the app runs.
 */

const NS = "test-order-ns";

const EQUIPMENT_LIKE: FrontendModule = {
  name: "test-order-overrides",
  routes: [],
  i18nOverrides: {
    en: {
      [`${NS}:nav.items`]: "Assets",
      [`${NS}:nav.storages`]: "Locations",
    },
  },
};

// The catalog as the backend serves it: no override values in it.
const CATALOG: Record<string, unknown> = {
  nav: { items: "Products", storages: "Storages" },
};

// The shape a module declares when it renames the vocabulary rather than
// one label: the heading key (`items:title`) rides along with the tab key.
// No module in the tree declares overrides today — the declaration this
// fixture once modelled was withdrawn — so it stands for the contract the
// second describe documents, not for a declaration production carries.
const EQUIPMENT_LIKE_WITH_TITLES: FrontendModule = {
  name: "test-order-titles",
  routes: [],
  i18nOverrides: {
    en: {
      "inventory:nav.items": "Assets",
      "inventory:nav.storages": "Locations",
      "items:title": "Assets",
      "locations:title": "Locations",
    },
    pl: {
      "inventory:nav.items": "Zasoby",
      "inventory:nav.storages": "Lokalizacje",
      "items:title": "Zasoby",
      "locations:title": "Lokalizacje",
    },
  },
};

/**
 * A catalog arriving from the backend: i18next merges it shallowly, then the
 * registry is told (the order `src/i18n/config.ts` uses).
 */
function catalogLands(bundle: Record<string, unknown>, lang = "en"): void {
  i18n.addResourceBundle(lang, NS, bundle);
  moduleRegistry.catalogLoaded(lang, NS, bundle);
}

function label(): string {
  return i18n.t(`${NS}:nav.items`, { lng: "en" });
}

describe("nav labels survive catalog registration order", () => {
  afterEach(() => {
    // Reverts the standing overrides and restores the pristine bundles the
    // first application saved, so the next test reads the real catalog.
    moduleRegistry.applyI18nOverrides([]);
    i18n.removeResourceBundle("en", NS);
  });

  it("catalog registered first, overrides applied after: the override wins", () => {
    catalogLands(CATALOG);
    moduleRegistry.register(EQUIPMENT_LIKE);
    moduleRegistry.applyI18nOverrides([EQUIPMENT_LIKE.name]);

    expect(label()).toBe("Assets");
  });

  it("overrides applied first, catalog lands later: the override still wins", () => {
    // The chunk with the renames loads and applies while the catalog's own
    // chunk is still in flight.
    moduleRegistry.register(EQUIPMENT_LIKE);
    moduleRegistry.applyI18nOverrides([EQUIPMENT_LIKE.name]);
    expect(label()).toBe("Assets");

    // The catalog lands late — it must not bury the standing override, or
    // the same reload flips the label back.
    catalogLands(CATALOG);

    expect(label()).toBe("Assets");
  });

  it("a later removal restores the catalog, not the pre-catalog state", () => {
    // The snapshot an override removal restores from has to include the
    // catalog that landed after the override — restoring the empty state it
    // captured would take the namespace's own keys down with the rename.
    moduleRegistry.register(EQUIPMENT_LIKE);
    moduleRegistry.applyI18nOverrides([EQUIPMENT_LIKE.name]);
    catalogLands(CATALOG);
    expect(label()).toBe("Assets");

    moduleRegistry.applyI18nOverrides([]);

    expect(label()).toBe("Products");
  });
});

/**
 * Control, not proof of the re-application above: both cases are green with
 * and without the mechanism (measured — removing the `reapplyOverrides…`
 * call from `noteCatalogLanded` reddens the first describe's late-catalog
 * cases and the core-namespace case below, never these two). They document
 * the declaration contract the fixture models — the tab and the heading
 * answer the same word — so a declaration that splits the vocabulary trips
 * here. The ordering regression itself is the first describe's job.
 */
describe("the tab and the heading spell the same word (control)", () => {
  // With the module enabled both keys answer the override, with it disabled
  // both answer the base catalog; neither case depends on which chunk lands
  // first. The defect this pins is a heading that reads `items:title` while
  // the tab reads the renamed key — the reader clicked "Zasoby" onto a page
  // titled "Produkty", with no race involved.
  afterEach(() => {
    moduleRegistry.applyI18nOverrides([]);
  });

  it("module enabled: heading key and tab key agree on the override", () => {
    moduleRegistry.register(EQUIPMENT_LIKE_WITH_TITLES);
    moduleRegistry.applyI18nOverrides([
      "inventory",
      EQUIPMENT_LIKE_WITH_TITLES.name,
    ]);

    expect(i18n.t("inventory:nav.items", { lng: "en" })).toBe("Assets");
    expect(i18n.t("items:title", { lng: "en" })).toBe("Assets");
    expect(i18n.t("inventory:nav.items", { lng: "pl" })).toBe(
      i18n.t("items:title", { lng: "pl" }),
    );
  });

  it("module disabled: both keys fall back to the same base word", () => {
    moduleRegistry.applyI18nOverrides([]);

    expect(i18n.t("inventory:nav.items", { lng: "en" })).toBe(
      i18n.t("items:title", { lng: "en" }),
    );
    expect(i18n.t("inventory:nav.items", { lng: "pl" })).toBe(
      i18n.t("items:title", { lng: "pl" }),
    );
  });
});

/**
 * The re-application is not a module-registration trick: `noteCatalogLanded`
 * keys on the namespace a catalog lands in, and `src/i18n/config.ts` serves
 * the core namespaces — `common`, `items`, `storages` — through the same
 * dynamic backend as the modules' own. A module renaming core vocabulary
 * therefore keeps the ordering guarantee the first describe measures for a
 * module namespace, so the overrides gate need not reject core targets.
 *
 * What this fails on (measured): remove the `reapplyOverridesForNamespace`
 * call from `noteCatalogLanded` and the late catalog buries the rename —
 * the last assertion reads "Save", not "Stash away".
 */
describe("a core namespace is protected on the same terms", () => {
  const CORE_NS = "common";

  const CORE_OVERRIDE: FrontendModule = {
    name: "test-order-core-overrides",
    routes: [],
    i18nOverrides: { en: { "common:actions.save": "Stash away" } },
  };

  afterEach(() => {
    moduleRegistry.applyI18nOverrides([]);
  });

  it("a late catalog for a core namespace does not bury the override", () => {
    moduleRegistry.register(CORE_OVERRIDE);
    moduleRegistry.applyI18nOverrides([CORE_OVERRIDE.name]);
    expect(i18n.t("common:actions.save", { lng: "en" })).toBe("Stash away");

    // The backend shallow-merges the core catalog in and announces it — the
    // same landing a module catalog makes, for a namespace core owns.
    const catalog = { actions: { save: "Save" } };
    i18n.addResourceBundle("en", CORE_NS, catalog);
    moduleRegistry.catalogLoaded("en", CORE_NS, catalog);

    expect(i18n.t("common:actions.save", { lng: "en" })).toBe("Stash away");
  });
});
