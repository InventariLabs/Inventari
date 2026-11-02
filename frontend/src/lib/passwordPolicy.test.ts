import { describe, it, expect } from "vitest";
import {
  PASSWORD_MAX_BYTES,
  checkPasswordRules,
  firstBrokenRule,
} from "./passwordPolicy";

describe("passwordPolicy maxBytes", () => {
  it("accepts a password at the ceiling, diacritics included", () => {
    // 34 two-byte letters (68 bytes) + 'Aa1x' = 72 bytes, every other rule met.
    const atTheCeiling = "Ą".repeat(34) + "Aa1x";
    expect(checkPasswordRules(atTheCeiling)).toEqual({
      minLength: true,
      lowercase: true,
      uppercase: true,
      digit: true,
      maxBytes: true,
    });
    expect(firstBrokenRule(atTheCeiling)).toBeNull();
  });

  it("breaks only maxBytes one byte past the ceiling", () => {
    // 35 two-byte letters (70 bytes) + 'Aa1' = 73 bytes; character rules pass.
    const pastTheCeiling = "Ą".repeat(35) + "Aa1";
    expect(pastTheCeiling.length).toBeLessThanOrEqual(128);
    expect(firstBrokenRule(pastTheCeiling)).toBe("maxBytes");
  });

  it("counts ASCII length in bytes too", () => {
    expect(firstBrokenRule("a".repeat(PASSWORD_MAX_BYTES + 1) + "A1")).toBe(
      "maxBytes",
    );
  });
});
