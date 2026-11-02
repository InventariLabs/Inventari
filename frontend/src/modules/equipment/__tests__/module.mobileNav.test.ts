import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import "@/modules/equipment/module";

/**
 * Regression guard.
 *
 * Categories/Templates were unreachable on mobile (`showOnMobile: false` and
 * no item had `mobileBar`, so AppShell rendered everything in the bar and
 * never showed the "More" panel). The module now exposes all 8 pages on
 * mobile: 4 in the bottom bar, 3 under "More" (AppShell logic in
 * AppShell.tsx:101-113).
 */

describe("equipment module — mobile navigation", () => {
  const nav = moduleRegistry.getModuleNav("equipment");
  const mobile = (nav?.items ?? []).filter((i) => i.showOnMobile !== false);

  it("exposes all 8 pages on mobile (no showOnMobile: false)", () => {
    expect(nav).toBeDefined();
    expect(mobile).toHaveLength(8);
    const paths = mobile.map((i) => i.path);
    expect(paths).toContain("/equipment/categories");
    expect(paths).toContain("/equipment/templates");
  });

  it("puts exactly 4 items in the bottom bar and 4 under More", () => {
    const bar = mobile.filter((i) => i.mobileBar);
    const more = mobile.filter((i) => !i.mobileBar);
    expect(bar.map((i) => i.path).sort()).toEqual(
      [
        "/equipment",
        "/equipment/assets",
        "/equipment/my",
        "/equipment/locations",
      ].sort(),
    );
    expect(more.map((i) => i.path).sort()).toEqual(
      [
        "/equipment/categories",
        "/equipment/templates",
        "/equipment/campaigns",
        "/equipment/settings",
      ].sort(),
    );
  });
});
