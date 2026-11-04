import { describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { useTranslation } from "react-i18next";
import { formatQuantityLocalized, unitLabel } from "./i18nHelpers";

describe("a quantity with a unit that is a word", () => {
  const translator = () => renderHook(() => useTranslation()).result.current.t;

  it("writes the plural the number asks for", () => {
    const t = translator();
    expect(formatQuantityLocalized(t, 6, "bottle")).toBe("6 bottles");
    expect(formatQuantityLocalized(t, "1.000", "bottle")).toBe("1 bottle");
  });

  it("leaves a symbol as it is", () => {
    const t = translator();
    expect(formatQuantityLocalized(t, 6, "kg")).toBe("6 kg");
  });

  it("names the unit alone in its one form", () => {
    expect(unitLabel(translator(), "bottle")).toBe("bottle");
  });
});
