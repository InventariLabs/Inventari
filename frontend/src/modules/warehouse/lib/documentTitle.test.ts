import { describe, expect, it } from "vitest";
import { documentTitle } from "./documentTitle";

const t = (key: string, options?: Record<string, unknown>) =>
  key === "warehouse:draftTitle"
    ? `${options?.type} – draft ${options?.suffix}`
    : key === "warehouse:types.OUT"
      ? "Delivery"
      : key;

describe("documentTitle", () => {
  it("names a draft by its kind instead of its raw identifier", () => {
    expect(
      documentTitle(t, { number: "DRAFT-3CB4B1BD5F1C", type: "OUT" }),
    ).toBe("Delivery – draft 5F1C");
  });

  it("keeps the number of a document the register has numbered", () => {
    expect(documentTitle(t, { number: "WZ/2026/0002", type: "OUT" })).toBe(
      "WZ/2026/0002",
    );
  });

  it("keeps a register number that merely begins like an identifier", () => {
    // A format whose literal text starts with DRAFT- ends on a digit.
    expect(documentTitle(t, { number: "DRAFT-IN/2026/0003", type: "IN" })).toBe(
      "DRAFT-IN/2026/0003",
    );
    expect(documentTitle(t, { number: "DRAFT-000000000001", type: "IN" })).toBe(
      "DRAFT-000000000001",
    );
  });
});
