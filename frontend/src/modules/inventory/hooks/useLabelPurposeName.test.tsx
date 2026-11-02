import { renderHook } from "@testing-library/react";
import { Monitor } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useLabelPurposeName } from "./useLabelPurposeName";

/**
 * The pool stores the purpose as a bare tag; the name a reader sees comes
 * from the module that claimed it. A tag nobody claims (its module was
 * uninstalled) must still read as something, because a printed sheet of
 * those labels is still on somebody's shelf.
 */
describe("useLabelPurposeName", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const withClaim = () =>
    vi.spyOn(moduleRegistry, "getLabelPurposes").mockReturnValue([
      {
        contextTag: "equipment",
        icon: Monitor,
        // Any catalogue key will do: the hook only resolves it.
        labelKey: "labels:generateModal.types.category",
        defaultPrefix: "EQP",
      },
    ]);

  it("names a claimed tag by the claiming module's own wording", () => {
    withClaim();
    const { result } = renderHook(() => useLabelPurposeName());

    expect(result.current("equipment")).toBe("Category");
  });

  it("calls a label with no tag a product label", () => {
    withClaim();
    const { result } = renderHook(() => useLabelPurposeName());

    expect(result.current(null)).toBe("Products");
    expect(result.current(undefined)).toBe("Products");
  });

  it("shows the raw tag when no installed module claims it", () => {
    withClaim();
    const { result } = renderHook(() => useLabelPurposeName());

    expect(result.current("garden_tools")).toBe("garden_tools");
  });
});
