import { describe, it, expect } from "vitest";
import {
  NEUTRAL_BASE_FIELDS_ALWAYS_ON,
  NEUTRAL_BASE_FIELDS_TOGGLEABLE,
  NEUTRAL_BASE_FIELD_ICONS,
  NEUTRAL_BASE_FIELD_LABEL_KEYS,
  getNeutralBaseFields,
  type NeutralBaseFieldKey,
} from "./neutralBaseFields";

describe("neutralBaseFields", () => {
  describe("NEUTRAL_BASE_FIELDS_ALWAYS_ON", () => {
    it("contains exactly the three always-on keys (name, quantity, unit)", () => {
      expect([...NEUTRAL_BASE_FIELDS_ALWAYS_ON].sort()).toEqual(
        ["name", "quantity", "unit"].sort(),
      );
    });

    it("contains no food-biased keys", () => {
      const forbidden = [
        "freeze_date",
        "expiry_date",
        "production_date",
        "brand",
      ];
      for (const key of forbidden) {
        expect(NEUTRAL_BASE_FIELDS_ALWAYS_ON).not.toContain(key);
      }
    });
  });

  describe("NEUTRAL_BASE_FIELDS_TOGGLEABLE", () => {
    it("contains exactly the five optional keys (barcode, sku, price, notes, shelf_location)", () => {
      expect([...NEUTRAL_BASE_FIELDS_TOGGLEABLE].sort()).toEqual(
        ["barcode", "notes", "price", "shelf_location", "sku"].sort(),
      );
    });

    it("does not overlap with ALWAYS_ON", () => {
      const always = new Set<string>(NEUTRAL_BASE_FIELDS_ALWAYS_ON);
      for (const key of NEUTRAL_BASE_FIELDS_TOGGLEABLE) {
        expect(always.has(key)).toBe(false);
      }
    });

    it("contains no food/equipment-biased keys", () => {
      const forbidden = [
        "freeze_date",
        "expiry_date",
        "production_date",
        "brand",
        "serial_number",
        "manufacturer",
        "model",
        "equipment_status",
      ];
      for (const key of forbidden) {
        expect(NEUTRAL_BASE_FIELDS_TOGGLEABLE).not.toContain(key);
      }
    });
  });

  describe("NEUTRAL_BASE_FIELD_ICONS", () => {
    it("has an icon for every always-on key", () => {
      for (const key of NEUTRAL_BASE_FIELDS_ALWAYS_ON) {
        expect(NEUTRAL_BASE_FIELD_ICONS[key]).toBeDefined();
      }
    });

    it("has an icon for every toggleable key", () => {
      for (const key of NEUTRAL_BASE_FIELDS_TOGGLEABLE) {
        expect(NEUTRAL_BASE_FIELD_ICONS[key]).toBeDefined();
      }
    });
  });

  describe("NEUTRAL_BASE_FIELD_LABEL_KEYS", () => {
    it("has a label key for every always-on key", () => {
      for (const key of NEUTRAL_BASE_FIELDS_ALWAYS_ON) {
        expect(NEUTRAL_BASE_FIELD_LABEL_KEYS[key]).toBe(key);
      }
    });

    it("has a label key for every toggleable key", () => {
      for (const key of NEUTRAL_BASE_FIELDS_TOGGLEABLE) {
        expect(NEUTRAL_BASE_FIELD_LABEL_KEYS[key]).toBe(key);
      }
    });
  });

  describe("getNeutralBaseFields()", () => {
    it("returns the toggleable list (matches existing StorageEditSheet call shape)", () => {
      expect(getNeutralBaseFields()).toEqual([
        ...NEUTRAL_BASE_FIELDS_TOGGLEABLE,
      ]);
    });

    it("ignores contextTag (the storage is now neutral; vertical fields come from category)", () => {
      // Contract: the signature still accepts contextTag for migration ease,
      // but it must NOT branch on it. Passing 'freezer' must yield the same list
      // as passing 'equipment' or undefined.
      expect(getNeutralBaseFields("equipment")).toEqual(getNeutralBaseFields());
      expect(getNeutralBaseFields(undefined)).toEqual(getNeutralBaseFields());
    });
  });

  describe("NeutralBaseFieldKey type", () => {
    it("is a union of all base field keys (compile-time, but runtime-checked)", () => {
      const all: NeutralBaseFieldKey[] = [
        ...NEUTRAL_BASE_FIELDS_ALWAYS_ON,
        ...NEUTRAL_BASE_FIELDS_TOGGLEABLE,
      ];
      // All entries must be unique
      expect(new Set(all).size).toBe(all.length);
      // Must contain no junk
      expect(all.every((k) => typeof k === "string" && k.length > 0)).toBe(
        true,
      );
    });
  });
});
