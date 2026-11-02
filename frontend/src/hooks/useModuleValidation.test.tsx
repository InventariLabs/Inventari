/**
 * Module rules run inside core forms, so the contract is as much about what a
 * module *cannot* do as what it can.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { ValidationRule } from "@/lib/moduleRegistry/moduleInterfaces";
import {
  useModuleValidation,
  FORM_LEVEL_ERROR_KEY,
} from "./useModuleValidation";

// The registry is a module-level singleton and `register` skips a name it
// already holds, so each test gets its own module name and enables just that.
let enabled: string[] = [];
let counter = 0;

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabled,
}));

function wrapper({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function register(rules: ValidationRule[]) {
  const name = `demo_mod_${counter++}`;
  moduleRegistry.register({ name, routes: [], validationRules: rules });
  enabled = [name];
}

function run(formData: Record<string, unknown>) {
  const { result } = renderHook(() => useModuleValidation("item_create"), {
    wrapper,
  });
  return result.current(formData);
}

describe("useModuleValidation", () => {
  beforeEach(() => {
    enabled = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports the message a failing rule returns", () => {
    register([
      { form: "item_create", field: "name", validator: () => "too short" },
    ]);

    expect(run({ name: "x" })).toEqual({ name: "too short" });
  });

  it("reports nothing when the rule passes", () => {
    register([{ form: "item_create", field: "name", validator: () => null }]);

    expect(run({ name: "fine" })).toEqual({});
  });

  it("passes the field value and the whole form to the validator", () => {
    const validator = vi.fn(() => null);
    register([{ form: "item_create", field: "name", validator }]);

    run({ name: "widget", quantity: "2" });

    expect(validator).toHaveBeenCalledWith("widget", {
      name: "widget",
      quantity: "2",
    });
  });

  it("gives a cross-field rule the whole form under the form-level key", () => {
    register([
      {
        form: "item_create",
        field: "*",
        validator: (value, formData) =>
          value === undefined && formData.quantity === "0"
            ? "quantity must not be zero"
            : null,
      },
    ]);

    expect(run({ quantity: "0" })).toEqual({
      [FORM_LEVEL_ERROR_KEY]: "quantity must not be zero",
    });
  });

  it("skips a rule that throws instead of breaking the form", () => {
    // A module must not be able to wedge a core form shut.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    register([
      {
        form: "item_create",
        field: "name",
        priority: 1,
        validator: () => {
          throw new Error("boom");
        },
      },
      {
        form: "item_create",
        field: "brand",
        priority: 2,
        validator: () => "brand is required",
      },
    ]);

    expect(run({ name: "x" })).toEqual({ brand: "brand is required" });
    expect(spy).toHaveBeenCalled();
  });

  it("ignores rules aimed at another form", () => {
    register([
      { form: "item_edit", field: "name", validator: () => "edit only" },
    ]);

    expect(run({ name: "x" })).toEqual({});
  });

  it("lets the highest-priority rule own a field", () => {
    register([
      {
        form: "item_create",
        field: "name",
        priority: 10,
        validator: () => "first",
      },
      {
        form: "item_create",
        field: "name",
        priority: 20,
        validator: () => "second",
      },
    ]);

    expect(run({ name: "x" })).toEqual({ name: "first" });
  });
});
