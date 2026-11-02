import { describe, expect, it } from "vitest";
import { readableSku } from "./readableSku";

describe("readableSku", () => {
  it("hides the code the server mints when no SKU pattern is set", () => {
    expect(readableSku("STM-CD4E8B75")).toBeNull();
  });

  it("keeps a code somebody chose", () => {
    expect(readableSku("WAX-SOY-1KG")).toBe("WAX-SOY-1KG");
    expect(readableSku("STM-cd4e8b75")).toBe("STM-cd4e8b75");
    expect(readableSku("STM-CD4E8B75X")).toBe("STM-CD4E8B75X");
  });

  it("returns null for a missing code", () => {
    expect(readableSku(null)).toBeNull();
    expect(readableSku(undefined)).toBeNull();
    expect(readableSku("")).toBeNull();
  });
});
