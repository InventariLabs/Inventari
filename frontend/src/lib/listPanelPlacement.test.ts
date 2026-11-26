import { describe, expect, it } from "vitest";
import { placeListPanel } from "./listPanelPlacement";

const rect = { top: 437, bottom: 477, left: 20, width: 300 };

describe("placeListPanel", () => {
  it("opens below the input when the room is there", () => {
    const place = placeListPanel(
      { ...rect, top: 100, bottom: 140 },
      240,
      800,
      800,
    );
    expect(place.top).toBe(144);
    expect(place.bottom).toBeUndefined();
  });

  it("anchors an upward panel by its bottom edge to the input", () => {
    // 560 px window: 79 px below the input, so the list opens upward. A list
    // taller than the 240 px guess still ends 4 px above the input.
    const place = placeListPanel(rect, 240, 560, 560);
    expect(place.top).toBeUndefined();
    expect(place.bottom).toBe(560 - 437 + 4);
    expect(place.maxHeight).toBe(437 - 16);
  });

  it("measures the anchor against the layout viewport, not the visible one", () => {
    const place = placeListPanel(rect, 240, 560, 800);
    expect(place.bottom).toBe(800 - 437 + 4);
  });
});
