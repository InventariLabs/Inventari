import { describe, expect, it } from "vitest";
import { parseApiValidationErrors } from "./validationErrors";

describe("parseApiValidationErrors (422 → fields)", () => {
  const keyOf = (i: number) => `line-${i}-key`;

  it("maps body-level partner_id to partner_id", () => {
    const errs = parseApiValidationErrors(
      [{ loc: ["body", "partner_id"], msg: "required", type: "value_error" }],
      keyOf,
    );
    expect(errs).toEqual({ partner_id: "required" });
  });

  it("maps body-level source/target/notes/external_reference", () => {
    const errs = parseApiValidationErrors(
      [
        { loc: ["body", "source_location_id"], msg: "a", type: "x" },
        { loc: ["body", "target_location_id"], msg: "b", type: "x" },
        { loc: ["body", "notes"], msg: "c", type: "x" },
        { loc: ["body", "external_reference"], msg: "d", type: "x" },
      ],
      keyOf,
    );
    expect(errs).toEqual({
      source_location_id: "a",
      target_location_id: "b",
      notes: "c",
      external_reference: "d",
    });
  });

  it("maps line field expected_quantity to line.<key>.quantity (normalized)", () => {
    const errs = parseApiValidationErrors(
      [
        {
          loc: ["body", "lines", 0, "expected_quantity"],
          msg: "> 0",
          type: "gt",
        },
      ],
      keyOf,
    );
    expect(errs).toEqual({ "line.line-0-key.quantity": "> 0" });
  });

  it("maps line field quantity to line.<key>.quantity", () => {
    const errs = parseApiValidationErrors(
      [{ loc: ["body", "lines", 1, "quantity"], msg: "bad", type: "x" }],
      keyOf,
    );
    expect(errs).toEqual({ "line.line-1-key.quantity": "bad" });
  });

  it("maps line name to line.<key>.name", () => {
    const errs = parseApiValidationErrors(
      [{ loc: ["body", "lines", 0, "name"], msg: "Provide name", type: "x" }],
      keyOf,
    );
    expect(errs).toEqual({ "line.line-0-key.name": "Provide name" });
  });

  it("routes line item_id/product_template_id to line.<key>.name", () => {
    const errs = parseApiValidationErrors(
      [
        { loc: ["body", "lines", 0, "item_id"], msg: "missing", type: "x" },
        {
          loc: ["body", "lines", 0, "product_template_id"],
          msg: "missing",
          type: "x",
        },
      ],
      keyOf,
    );
    expect(errs).toEqual({ "line.line-0-key.name": "missing" });
  });

  it("buckets line-object errors (no trailing field) to _form", () => {
    const errs = parseApiValidationErrors(
      [
        {
          loc: ["body", "lines", 0],
          msg: "Provide item_id, product_template_id, or a name",
          type: "value_error",
        },
      ],
      keyOf,
    );
    expect(errs).toEqual({
      _form: "Provide item_id, product_template_id, or a name",
    });
  });

  it("buckets lines-min-length to _form", () => {
    const errs = parseApiValidationErrors(
      [
        {
          loc: ["body", "lines"],
          msg: "List should have at least 1 item",
          type: "too_short",
        },
      ],
      keyOf,
    );
    expect(errs).toEqual({ _form: "List should have at least 1 item" });
  });

  it("buckets bare body to _form", () => {
    const errs = parseApiValidationErrors(
      [{ loc: ["body"], msg: "Invalid", type: "x" }],
      keyOf,
    );
    expect(errs).toEqual({ _form: "Invalid" });
  });

  it("aggregates multiple errors into one record", () => {
    const errs = parseApiValidationErrors(
      [
        { loc: ["body", "partner_id"], msg: "p", type: "x" },
        {
          loc: ["body", "lines", 0, "expected_quantity"],
          msg: "q",
          type: "x",
        },
        { loc: ["body", "target_location_id"], msg: "t", type: "x" },
      ],
      keyOf,
    );
    expect(errs).toEqual({
      partner_id: "p",
      "line.line-0-key.quantity": "q",
      target_location_id: "t",
    });
  });

  it("maps structured {code,message,field}", () => {
    const errs = parseApiValidationErrors(
      { code: "VALIDATION_ERROR", message: "bad", field: "partner_id" },
      keyOf,
    );
    expect(errs).toEqual({ partner_id: "bad" });
  });

  it("maps structured {code,message} (no field) to _form", () => {
    const errs = parseApiValidationErrors(
      { code: "VALIDATION_ERROR", message: "bad" },
      keyOf,
    );
    expect(errs).toEqual({ _form: "bad" });
  });

  it("maps a string detail to _form", () => {
    const errs = parseApiValidationErrors("Something failed", keyOf);
    expect(errs).toEqual({ _form: "Something failed" });
  });

  it("returns {} for unknown shapes", () => {
    expect(parseApiValidationErrors(null, keyOf)).toEqual({});
    expect(parseApiValidationErrors(42, keyOf)).toEqual({});
    expect(parseApiValidationErrors(undefined, keyOf)).toEqual({});
  });

  it("falls back to numeric line index when indexToKey returns undefined", () => {
    const errs = parseApiValidationErrors(
      [{ loc: ["body", "lines", 3, "quantity"], msg: "x", type: "x" }],
      () => undefined,
    );
    expect(errs).toEqual({ "line.3.quantity": "x" });
  });
});
