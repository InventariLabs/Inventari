/**
 * example_widgets is the reference module — what it declares is what module
 * authors copy. `bulkActions` had a consumer (ItemsBulkActionBar) but no
 * producer anywhere in the repo, so this guards the example itself, not just
 * the registry plumbing that `moduleRegistry.test.ts` already covers.
 */
import { describe, it, expect, beforeAll, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import { moduleRegistry } from "@/lib/moduleRegistry";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("example_widgets module registration", () => {
  beforeAll(async () => {
    // Registration is an import side effect, same as in the real app entry.
    await import("../module");
  });

  it("contributes a bulk action when enabled", () => {
    const actions = moduleRegistry.getBulkActions(["example_widgets"]);
    const action = actions.find((a) => a.id === "copy-selected-ids");

    expect(action).toBeDefined();
    expect(action?.moduleName).toBe("example_widgets");
    expect(action?.labelKey).toBe("example_widgets:actions.copyIds");
  });

  // The launcher lists only modules that declare a tile. Without one, a module
  // copied from this one is switched on and then reachable only by its address.
  it("has a tile on the home screen when enabled", () => {
    const tile = moduleRegistry
      .getVisibleModules(["example_widgets"])
      .find((m) => m.name === "example_widgets")?.launcher;

    expect(tile?.displayName).toBe("modules:modules.example_widgets.name");
    expect(tile?.description).toBe(
      "modules:modules.example_widgets.description",
    );
  });

  it("contributes nothing when the module is disabled", () => {
    const actions = moduleRegistry.getBulkActions([]);

    expect(actions.find((a) => a.id === "copy-selected-ids")).toBeUndefined();
  });
});

describe("example_widgets contributions at work", () => {
  beforeAll(async () => {
    await import("../module");
  });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  const copyAction = () =>
    moduleRegistry
      .getBulkActions(["example_widgets"])
      .find((a) => a.id === "copy-selected-ids")!;

  it("copies the selected identifiers, one per line, and says so", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    await copyAction().handler(["id-1", "id-2"]);

    expect(writeText).toHaveBeenCalledWith("id-1\nid-2");
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("copied to the clipboard"),
    );
  });

  it("claims no success when the clipboard is not there", async () => {
    // Over plain http the clipboard does not exist; a "copied" toast then
    // would send the reader to paste nothing.
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });

    await copyAction().handler(["id-1"]);

    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  describe("the name rule on the product form", () => {
    const rule = () =>
      moduleRegistry
        .getValidationRules("item_create", ["example_widgets"])
        .find((r) => r.field === "name")!;

    it("refuses a name made only of digits, the mark of a mis-scan", () => {
      expect(rule().validator("5901234123457", {})).toContain(
        "looks like a product code",
      );
      expect(rule().validator("  42 ", {})).not.toBeNull();
    });

    it("lets a real name and a name with digits through", () => {
      expect(rule().validator("Milk 2%", {})).toBeNull();
      expect(rule().validator("", {})).toBeNull();
    });
  });
});
