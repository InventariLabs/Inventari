import { describe, it, expect, beforeEach } from "vitest";
import { useFormMemoryStore } from "./formMemoryStore";

describe("useFormMemoryStore", () => {
  beforeEach(() => {
    useFormMemoryStore.setState({ lastItem: null });
  });

  it("initializes with null lastItem", () => {
    expect(useFormMemoryStore.getState().lastItem).toBeNull();
  });

  it("remembers where the batch is going and what it is", () => {
    useFormMemoryStore.getState().setLastItem({
      category_id: "cat-1",
      location_id: "sl-1",
    });

    const stored = useFormMemoryStore.getState().lastItem;
    expect(stored?.category_id).toBe("cat-1");
    expect(stored?.location_id).toBe("sl-1");
  });

  it("remembers nothing that describes one product", () => {
    // The name, the brand, the weight, the expiry date and the custom fields
    // used to travel too. On the next product they were data nobody typed —
    // and the expiry date of the carton before it is the kind of wrong that
    // does not look wrong. A payload carrying them changes nothing here.
    const payload = {
      category_id: "cat-1",
      location_id: "sl-1",
      name: "Milk",
      brand: "Brand A",
      expiry_date: "2026-12-01",
      weight_value: 500,
      metadata: { opened: true },
    };

    useFormMemoryStore.getState().setLastItem(payload);

    expect(useFormMemoryStore.getState().lastItem).toEqual({
      category_id: "cat-1",
      location_id: "sl-1",
    });
  });

  it("treats a cleared field as nothing to remember", () => {
    useFormMemoryStore
      .getState()
      .setLastItem({ location_id: "sl-1", category_id: null });
    expect(useFormMemoryStore.getState().lastItem?.category_id).toBeUndefined();
  });

  it("clear resets lastItem to null", () => {
    useFormMemoryStore.getState().setLastItem({ location_id: "sl-1" });
    useFormMemoryStore.getState().clear();
    expect(useFormMemoryStore.getState().lastItem).toBeNull();
  });
});
