import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Item } from "@/types";
import ProductNutritionOnItemSlot from "./ProductNutritionOnItemSlot";

const item = (metadata: Record<string, unknown>) =>
  ({ metadata, template: null }) as unknown as Item;

describe("ProductNutritionOnItemSlot — where the figures come from", () => {
  it("says figures filled from Open Food Facts are community data to check", () => {
    render(
      <ProductNutritionOnItemSlot
        data={{
          item: item({
            source: "local_off_db",
            nutrition: { energy_kcal: 321 },
          }),
        }}
      />,
    );
    expect(screen.getByTestId("community-data-note")).toHaveTextContent(
      /community database.*estimate.*label/i,
    );
  });

  it("adds nothing under figures that were typed in", () => {
    render(
      <ProductNutritionOnItemSlot
        data={{ item: item({ nutrition: { energy_kcal: 321 } }) }}
      />,
    );
    expect(screen.queryByTestId("community-data-note")).not.toBeInTheDocument();
  });
});
