import { describe, expect, it } from "vitest";

import { moduleRegistry, resolveModuleTarget } from "@/lib/moduleRegistry";
import "../module";

describe("the warehouse module opens on the floor's work", () => {
  it("lands on To do rather than the document list", () => {
    const module = moduleRegistry.getModule("warehouse");
    expect(module).toBeDefined();
    expect(resolveModuleTarget(module!)).toBe("/warehouse/todo");
  });

  it("keeps the former document list reachable from History, not as a tab", () => {
    const items = moduleRegistry.getModule("warehouse")?.moduleNav?.items ?? [];
    const list = items.find((item) => item.path === "/warehouse/all");
    // It carries the page's title for the shell but is no tab on any screen.
    expect(list).toBeDefined();
    expect(list?.titleKey).toBe("warehouse:title");
    expect(list?.showOnDesktop).toBe(false);
    expect(list?.showOnMobile).toBe(false);
  });
});
