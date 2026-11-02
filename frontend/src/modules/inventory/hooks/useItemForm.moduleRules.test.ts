/**
 * A module rule really blocks a save in a core form (acceptance).
 *
 * `validationRules` was a declared-but-unwired extension point: the registry
 * collected rules and no form ever asked for them. These tests exercise the
 * whole path — module declares, core form runs it, submit is refused.
 */
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { QueryWrapper } from "@/test/queryWrapper";
import type { ValidationRule } from "@/lib/moduleRegistry/moduleInterfaces";
import { useItemForm } from "./useItemForm";

let enabled: string[] = [];
let counter = 0;

// The form reads the "Show inventory value" switch through the stats
// module's query; this file renders without that module's providers.
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => true,
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabled,
}));

function registerRules(rules: ValidationRule[]) {
  const name = `rulemod_${counter++}`;
  moduleRegistry.register({ name, routes: [], validationRules: rules });
  enabled = [name];
}

/** A form filled in well enough that core validation alone would pass. */
function fillValid(result: { current: ReturnType<typeof useItemForm> }) {
  act(() => {
    result.current.setFormData((prev) => ({
      ...prev,
      name: "12345",
      location_id: "loc-1",
    }));
  });
}

describe("useItemForm — module validation rules", () => {
  beforeEach(() => {
    enabled = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("blocks submit and shows the module's message", () => {
    const onSubmit = vi.fn();
    registerRules([
      {
        form: "item_create",
        field: "name",
        validator: (value) =>
          typeof value === "string" && /^\d+$/.test(value)
            ? "that looks like a barcode"
            : null,
      },
    ]);

    const { result } = renderHook(() => useItemForm({ onSubmit }), {
      wrapper: QueryWrapper,
    });
    fillValid(result);
    act(() => result.current.submit());

    expect(onSubmit).not.toHaveBeenCalled();
    expect(result.current.errors.name).toBe("that looks like a barcode");
  });

  it("lets the save through when the rule passes", () => {
    const onSubmit = vi.fn();
    registerRules([
      { form: "item_create", field: "name", validator: () => null },
    ]);

    const { result } = renderHook(() => useItemForm({ onSubmit }), {
      wrapper: QueryWrapper,
    });
    fillValid(result);
    act(() => result.current.submit());

    expect(onSubmit).toHaveBeenCalled();
  });

  it("does not let a module message mask a core one", () => {
    // Core owns its own fields; a module may only report what core did not.
    const onSubmit = vi.fn();
    registerRules([
      {
        form: "item_create",
        field: "name",
        validator: () => "module complaint",
      },
    ]);

    const { result } = renderHook(() => useItemForm({ onSubmit }), {
      wrapper: QueryWrapper,
    });
    act(() => {
      result.current.setFormData((prev) => ({
        ...prev,
        name: "",
        location_id: "loc-1",
      }));
    });
    act(() => result.current.submit());

    expect(result.current.errors.name).not.toBe("module complaint");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("survives a rule that throws, and still saves", () => {
    // The failure mode that would otherwise make this feature dangerous:
    // a broken module rule leaving the user unable to save anything.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const onSubmit = vi.fn();
    registerRules([
      {
        form: "item_create",
        field: "name",
        validator: () => {
          throw new Error("rule is broken");
        },
      },
    ]);

    const { result } = renderHook(() => useItemForm({ onSubmit }), {
      wrapper: QueryWrapper,
    });
    fillValid(result);
    act(() => result.current.submit());

    expect(onSubmit).toHaveBeenCalled();
    expect(spy).toHaveBeenCalled();
  });

  it("ignores a rule written for the other form", () => {
    const onSubmit = vi.fn();
    registerRules([
      {
        form: "item_edit",
        field: "name",
        validator: () => "edit-only complaint",
      },
    ]);

    const { result } = renderHook(() => useItemForm({ onSubmit }), {
      wrapper: QueryWrapper,
    });
    fillValid(result);
    act(() => result.current.submit());

    expect(onSubmit).toHaveBeenCalled();
  });

  it("applies the same rule when the form declares itself as the edit form", () => {
    const onSubmit = vi.fn();
    registerRules([
      {
        form: "item_edit",
        field: "name",
        validator: () => "edit-only complaint",
      },
    ]);

    const { result } = renderHook(
      () => useItemForm({ onSubmit, form: "item_edit" }),
      { wrapper: QueryWrapper },
    );
    fillValid(result);
    act(() => result.current.submit());

    expect(onSubmit).not.toHaveBeenCalled();
    expect(result.current.errors.name).toBe("edit-only complaint");
  });
});
