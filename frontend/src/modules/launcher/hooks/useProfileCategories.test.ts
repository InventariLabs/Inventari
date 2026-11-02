import { describe, it, expect } from "vitest";
import {
  resolveProfileCategory,
  resolveProfileCategories,
} from "./useProfileCategories";
import type { LauncherCategory, ProductProfile } from "@/types";
import type { FrontendModule } from "@/lib/moduleRegistry";
import {
  Star,
  Briefcase,
  BarChart3,
  Plug,
  Settings as SettingsIcon,
} from "lucide-react";

function makeProfile(
  id: string,
  launcher_categories: Record<string, LauncherCategory> = {},
): ProductProfile {
  return {
    id,
    name: id,
    description: "",
    default_modules: Object.keys(launcher_categories),
    seed_profile: id,
    launcher_categories,
  };
}

function makeMod(
  name: string,
  category: LauncherCategory = "business",
): FrontendModule {
  return {
    name,
    routes: [],
    launcher: {
      displayName: name,
      icon: (() => {
        switch (category) {
          case "core":
            return Star;
          case "business":
            return Briefcase;
          case "analytics":
            return BarChart3;
          case "integrations":
            return Plug;
          case "system":
            return SettingsIcon;
        }
      })(),
      category,
    },
  };
}

describe("resolveProfileCategory", () => {
  it("returns profile override when present", () => {
    const profile = makeProfile("p", { items: "analytics" });
    const mod = makeMod("items", "business");
    expect(resolveProfileCategory(mod, profile)).toBe("analytics");
  });

  it("falls back to module launcher.category when profile has no override", () => {
    const profile = makeProfile("p", {});
    const mod = makeMod("items", "system");
    expect(resolveProfileCategory(mod, profile)).toBe("system");
  });

  it("falls back to 'business' when both are missing", () => {
    const profile = makeProfile("p", {});
    const mod: FrontendModule = { name: "items", routes: [] };
    expect(resolveProfileCategory(mod, profile)).toBe("business");
  });

  it("falls back to 'business' when profile is null", () => {
    const mod = makeMod("items", "system");
    expect(resolveProfileCategory(mod, null)).toBe("system");
  });
});

describe("resolveProfileCategories", () => {
  it("returns map of module name -> resolved category", () => {
    const profile = makeProfile("p", {
      items: "analytics",
      locations: "business",
    });
    const mods = [makeMod("items", "business"), makeMod("locations", "core")];
    const result = resolveProfileCategories(mods, profile);
    expect(result).toEqual({
      items: "analytics",
      locations: "business",
    });
  });

  it("preserves module order", () => {
    const profile = makeProfile("p", {});
    const mods = [makeMod("a"), makeMod("b"), makeMod("c")];
    const result = resolveProfileCategories(mods, profile);
    expect(Object.keys(result)).toEqual(["a", "b", "c"]);
  });

  it("returns empty map when given empty input", () => {
    expect(resolveProfileCategories([], makeProfile("p", {}))).toEqual({});
  });

  it("returns module defaults when profile is null", () => {
    const mods = [makeMod("a", "core"), makeMod("b", "analytics")];
    const result = resolveProfileCategories(mods, null);
    expect(result).toEqual({ a: "core", b: "analytics" });
  });
});
