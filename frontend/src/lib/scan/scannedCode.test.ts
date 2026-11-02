import { describe, expect, it } from "vitest";
import { scannedCode } from "./scannedCode";

describe("scannedCode", () => {
  it.each([
    "https://wh.example.test/labels/scan/A-02-01",
    "https://wh.example.test/s/A-02-01",
    "https://wh.example.test/scan?code=A-02-01",
    "  A-02-01\n",
  ])("reads %s as the shelf code", (raw) => {
    expect(scannedCode(raw)).toBe("A-02-01");
  });

  it("decodes a code that was quoted in the address", () => {
    expect(scannedCode("https://wh.example.test/s/IN/2026/0001")).toBe(
      "IN/2026/0001",
    );
    expect(scannedCode("https://wh.example.test/s/A%20B%231")).toBe("A B#1");
  });

  it.each([
    "5901234123457",
    "https://elsewhere.example/docs/page",
    "https://wh.example.test/s/",
    "http://[wh/s/STM-K9XP",
  ])("leaves %s as it was read", (raw) => {
    expect(scannedCode(raw)).toBe(raw);
  });
});
