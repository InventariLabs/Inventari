import { afterEach, describe, it, expect, vi } from "vitest";
import i18n from "i18next";

import type { FrontendModule } from "./moduleInterfaces";
import { applyI18nOverrides, noteCatalogLanded } from "./registryI18nTheme";

/**
 * The unit suite's i18n setup (src/test/mocks/i18n.ts) runs the real i18next
 * with the real bundles, `inventory` namespace included — so these assertions
 * exercise the same key resolution the sidebar uses, not a stand-in.
 */

/** A module that has listed every key it overrides as adopted. */
function makeModule(
  name: string,
  i18nOverrides: Record<string, Record<string, string>>,
  adoptedI18nKeys: string[] = Object.values(i18nOverrides).flatMap(Object.keys),
): FrontendModule {
  return { name, routes: [], i18nOverrides, adoptedI18nKeys };
}

function harness(...modules: FrontendModule[]) {
  return {
    modules: new Map(modules.map((m) => [m.name, m])),
    applied: new Set<string>(),
    saved: new Map<string, Record<string, unknown>>(),
  };
}

describe("applyI18nOverrides", () => {
  it("an override of a namespaced nav key reaches t() while enabled", () => {
    const mod = makeModule("test-i18n-assets", {
      en: { "inventory:nav.items": "Assets" },
    });
    const h = harness(mod);

    expect(i18n.t("inventory:nav.items")).toBe("Products");

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.items")).toBe("Assets");

    applyI18nOverrides([], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.items")).toBe("Products");
  });

  it("a dotted key nests into the bundle tree instead of landing beside it", () => {
    // Regression: addResourceBundle stored "navigation.items" as a flat key
    // next to the existing navigation:{...} tree, and t() kept resolving the
    // nested original — the override never reached the screen.
    const mod = makeModule("test-i18n-nesting", {
      en: { "navigation.items": "Things" },
    });
    const h = harness(mod);

    expect(i18n.t("common:navigation.items")).toBe("Products");

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    expect(i18n.t("common:navigation.items")).toBe("Things");

    applyI18nOverrides([], h.modules, h.applied, h.saved);
    expect(i18n.t("common:navigation.items")).toBe("Products");
  });

  it("a key without a namespace prefix lands in the common namespace", () => {
    const mod = makeModule("test-i18n-default-ns", {
      en: { "navigation.storages": "Places" },
    });
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    expect(i18n.t("common:navigation.storages")).toBe("Places");

    applyI18nOverrides([], h.modules, h.applied, h.saved);
    expect(i18n.t("common:navigation.storages")).toBe("Locations");
  });

  it("disabling one module keeps another module's overrides in place", () => {
    const first = makeModule("test-i18n-first", {
      en: { "inventory:nav.items": "Assets" },
    });
    const second = makeModule("test-i18n-second", {
      en: { "inventory:nav.storages": "Sites" },
    });
    const h = harness(first, second);

    applyI18nOverrides([first.name], h.modules, h.applied, h.saved);
    applyI18nOverrides(
      [first.name, second.name],
      h.modules,
      h.applied,
      h.saved,
    );
    expect(i18n.t("inventory:nav.items")).toBe("Assets");
    expect(i18n.t("inventory:nav.storages")).toBe("Sites");

    // The first module goes off; the second one's override must survive the
    // restore of the first one's snapshot.
    applyI18nOverrides([second.name], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.items")).toBe("Products");
    expect(i18n.t("inventory:nav.storages")).toBe("Sites");

    applyI18nOverrides([], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.storages")).toBe("Locations");
  });

  it("re-enable after disable applies the override again", () => {
    const mod = makeModule("test-i18n-reenable", {
      en: { "inventory:nav.items": "Assets" },
    });
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    applyI18nOverrides([], h.modules, h.applied, h.saved);
    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.items")).toBe("Assets");

    applyI18nOverrides([], h.modules, h.applied, h.saved);
    expect(i18n.t("inventory:nav.items")).toBe("Products");
  });
});

describe("an override key that matches nothing", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is named in development, and a key that exists is not", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const mod = makeModule("test-i18n-unmatched", {
      en: {
        "inventory:nav.items": "Assets",
        "inventory:nav.itemz": "Assets",
      },
    });
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    applyI18nOverrides([], h.modules, h.applied, h.saved);

    const said = warn.mock.calls.map((call) => String(call[0]));
    expect(said).toHaveLength(1);
    expect(said[0]).toContain('"test-i18n-unmatched"');
    expect(said[0]).toContain("inventory:nav.itemz");
    expect(said[0]).not.toContain("inventory:nav.items,");
  });

  it("is read against a catalog that lands after the override applied", () => {
    // No catalog yet for this language: nothing can be said at apply time,
    // and nothing is — every key would look missing.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const mod = makeModule("test-i18n-late", {
      xx: { "latens:title": "Renamed", "latens:titel": "Renamed" },
    });
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);
    expect(warn).not.toHaveBeenCalled();

    noteCatalogLanded(
      "xx",
      "latens",
      { title: "Original" },
      h.modules,
      h.applied,
      h.saved,
    );
    applyI18nOverrides([], h.modules, h.applied, h.saved);

    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("latens:titel");
  });
});

describe("overrides outside the module's own namespace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("a key of another namespace that is not adopted changes nothing, and is named", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const mod = makeModule(
      "test-i18n-stranger",
      { en: { "inventory:nav.items": "Assets" } },
      [],
    );
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);

    expect(i18n.t("inventory:nav.items")).toBe("Products");
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('"test-i18n-stranger"');
    expect(String(warn.mock.calls[0][0])).toContain("inventory:nav.items");
    applyI18nOverrides([], h.modules, h.applied, h.saved);
  });

  it("a key of the module's own namespace needs no listing", () => {
    // The namespace is the module's name; the catalog for it is not loaded
    // in this suite, so the override is read back from the store.
    const mod = makeModule("ownns", { en: { "ownns:title": "Mine" } }, []);
    const h = harness(mod);

    applyI18nOverrides([mod.name], h.modules, h.applied, h.saved);

    expect(i18n.t("ownns:title")).toBe("Mine");
    applyI18nOverrides([], h.modules, h.applied, h.saved);
  });

  it("two modules overriding one key are named together in development", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const first = makeModule("test-i18n-clash-a", {
      en: { "inventory:nav.items": "Assets" },
    });
    const second = makeModule("test-i18n-clash-b", {
      en: { "inventory:nav.items": "Goods" },
    });
    const h = harness(first, second);

    applyI18nOverrides(
      [first.name, second.name],
      h.modules,
      h.applied,
      h.saved,
    );

    const said = warn.mock.calls.map((call) => String(call[0]));
    const clash = said.filter((line) => line.includes("both override"));
    expect(clash).toHaveLength(1);
    expect(clash[0]).toContain('"test-i18n-clash-a"');
    expect(clash[0]).toContain('"test-i18n-clash-b"');
    expect(clash[0]).toContain("inventory:nav.items");
    applyI18nOverrides([], h.modules, h.applied, h.saved);
  });
});
