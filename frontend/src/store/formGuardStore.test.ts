import { beforeEach, describe, expect, it } from "vitest";
import { useFormGuardStore } from "./formGuardStore";

/**
 * One slot, one page: the store holds at most the label of the form the
 * reader is currently in. The label is already localized — the store only
 * carries it.
 */
describe("formGuardStore", () => {
  beforeEach(() => {
    useFormGuardStore.getState().setDirtyForm(null);
  });

  it("holds the label of a dirty form", () => {
    useFormGuardStore.getState().setDirtyForm("The asset form");
    expect(useFormGuardStore.getState().dirtyForm).toBe("The asset form");
  });

  it("clears when the form is no longer dirty", () => {
    useFormGuardStore.getState().setDirtyForm("The asset form");
    useFormGuardStore.getState().setDirtyForm(null);
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();
  });
});
