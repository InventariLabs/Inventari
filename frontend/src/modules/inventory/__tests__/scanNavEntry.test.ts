import { describe, expect, it } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { CORE_SECTION_NAV } from "@/lib/moduleRegistry/coreSections";
import "../module";

// A USB scanner sits at a desktop; the Scan screen it types into used to be
// reachable there only through the command palette.
describe("the Scan entry in the module menu", () => {
  it("is shown on desktop in the inventory menu", () => {
    const item = moduleRegistry
      .getModule("inventory")
      ?.moduleNav?.items.find((i) => i.path === "/inventory/scan");
    expect(item).toBeDefined();
    expect(item?.showOnDesktop).not.toBe(false);
  });

  it("is shown on desktop where a module adopts the section", () => {
    expect(CORE_SECTION_NAV.scan.showOnDesktop).not.toBe(false);
  });
});
