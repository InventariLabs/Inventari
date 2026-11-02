import { renderHook } from "@testing-library/react";
import { describe, it, expect } from "vitest";

import { useProfileLabels } from "./useProfileLabels";
import { withLanguage } from "@/test/mocks/i18n";

/** A shipped profile as GET /onboarding/profiles returns it — English fields. */
const CLEAN_CORE = {
  id: "clean_core",
  name: "Custom",
  description: "No industry preset — a neutral base you shape yourself.",
};

/** A profile the frontend cannot know at build time (community distribution). */
const THIRD_PARTY = {
  id: "vineyard_ops",
  name: "Vineyard Ops",
  description: "Barrels, blocks and harvest lots.",
};

describe("useProfileLabels", () => {
  it("resolves a shipped profile from the catalog, not from the API fields", async () => {
    // Mount inside the language switch: the resolver is bound to `t` at
    // render time, so a hook rendered in English would keep answering in it.
    await withLanguage("pl", () => {
      const { result, unmount } = renderHook(() => useProfileLabels());
      const labels = result.current(CLEAN_CORE);
      // Unmount before withLanguage restores English — a hook still mounted
      // would re-render on the restore, outside act().
      unmount();
      expect(labels.name).toBe("Własny");
      expect(labels.description).toBe(
        "Bez profilu branżowego — neutralna baza, którą kształtujesz po swojemu.",
      );
    });
  });

  it("falls back to the API fields for a profile outside the distribution", () => {
    const { result } = renderHook(() => useProfileLabels());
    const labels = result.current(THIRD_PARTY);
    expect(labels.name).toBe("Vineyard Ops");
    expect(labels.description).toBe("Barrels, blocks and harvest lots.");
  });

  it("never leaks the profile id as a label", () => {
    const { result } = renderHook(() => useProfileLabels());
    for (const id of ["food_home", "equipment_wms", "clean_core"]) {
      const labels = result.current({ id, name: "", description: "" });
      expect(labels.name).not.toContain(id);
      expect(labels.name.trim()).not.toBe("");
    }
  });
});
