import { describe, it, expect } from "vitest";
import { buildSubmissionPayload } from "./buildSubmissionPayload";
import type { FieldDefinition } from "@/types";

const field = (
  key: string,
  visible = true,
  isCustom = false,
): FieldDefinition =>
  ({
    key,
    label: key,
    type: "text",
    visible,
    required: false,
    is_system: false,
    is_custom: isCustom,
  }) as FieldDefinition;

const FIELDS = [
  field("category_id"),
  field("brand"),
  field("expiry_date"),
  field("weight"),
];

describe("buildSubmissionPayload", () => {
  it("sends an emptied optional field as an explicit null when editing", () => {
    // The whole of the "save that saved nothing": the key used to be dropped,
    // which the API cannot tell from a field the form never had.
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        category_id: "",
        brand: "",
      },
      FIELDS,
      "update",
    ) as Record<string, unknown>;

    expect("category_id" in payload).toBe(true);
    expect(payload.category_id).toBeNull();
    expect(payload.brand).toBeNull();
  });

  it("says nothing about a field the form does not have", () => {
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        category_id: undefined,
      },
      FIELDS,
      "update",
    ) as Record<string, unknown>;

    expect("category_id" in payload).toBe(false);
  });

  it("says nothing about a field this profile does not ask about", () => {
    // Hidden is not emptied: the record keeps whatever it holds.
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        category_id: "",
      },
      [field("category_id", false)],
      "update",
    ) as Record<string, unknown>;

    expect("category_id" in payload).toBe(false);
  });

  it("drops empty optional fields on a new product", () => {
    // Nothing to clear on a record that does not exist yet, and a create
    // payload full of nulls would only make the API argue about them.
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        category_id: "",
        brand: "",
      },
      FIELDS,
      "create",
    ) as Record<string, unknown>;

    expect("category_id" in payload).toBe(false);
    expect("brand" in payload).toBe(false);
  });

  it("never clears the fields that carry the record's identity", () => {
    const payload = buildSubmissionPayload(
      { name: "", location_id: "", quantity: "" },
      FIELDS,
      "update",
    ) as Record<string, unknown>;

    expect("name" in payload).toBe(false);
    expect("location_id" in payload).toBe(false);
    expect(payload.quantity).toBe(0);
  });

  it("clears the weight unit along with the weight it belonged to", () => {
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        weight: "",
        weight_uom_id: "uom-g",
      },
      FIELDS,
      "update",
    ) as Record<string, unknown>;

    expect(payload.weight_value).toBeNull();
    expect(payload.weight_uom_id).toBeNull();
  });

  it("keeps sending a filled weight as the unit weight it is", () => {
    const payload = buildSubmissionPayload(
      {
        name: "Canned peas",
        location_id: "sl-1",
        quantity: "2",
        weight: "400",
        weight_uom_id: "uom-g",
      },
      FIELDS,
      "update",
    ) as Record<string, unknown>;

    expect(payload.weight_value).toBe(400);
    expect(payload.weight_uom_id).toBe("uom-g");
    expect("weight" in payload).toBe(false);
  });

  describe("a value the form was handed for a hidden field", () => {
    const HIDDEN_BARCODE = [...FIELDS, field("barcode", false)];

    it("saves it on a new product instead of dropping it", () => {
      // A barcode carried in from a scan reaches the form through the
      // address, into data the user never sees an input for. The profile
      // hiding the field must not turn into the record losing the code.
      const payload = buildSubmissionPayload(
        {
          name: "Canned peas",
          location_id: "sl-1",
          quantity: "1",
          barcode: "REV3-A1B2C3",
        },
        HIDDEN_BARCODE,
        "create",
      ) as Record<string, unknown>;

      expect(payload.barcode).toBe("REV3-A1B2C3");
    });

    it("still says nothing about a hidden field that arrived empty", () => {
      const payload = buildSubmissionPayload(
        {
          name: "Canned peas",
          location_id: "sl-1",
          quantity: "1",
          barcode: "",
        },
        HIDDEN_BARCODE,
        "create",
      ) as Record<string, unknown>;

      expect("barcode" in payload).toBe(false);
    });

    it("keeps staying put when editing an existing record", () => {
      // The update path is the profile's word being final: a field it hides
      // is not pushed, in either direction.
      const payload = buildSubmissionPayload(
        {
          name: "Canned peas",
          location_id: "sl-1",
          quantity: "1",
          barcode: "REV3-A1B2C3",
        },
        HIDDEN_BARCODE,
        "update",
      ) as Record<string, unknown>;

      expect("barcode" in payload).toBe(false);
    });
  });
});
