import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { SelectedProductCard } from "./SelectedProductCard";
import type { ProductOption } from "@/modules/maker/api/products";

function renderCard(sku: string | null) {
  render(
    <SelectedProductCard
      product={
        {
          product_template_id: "tpl-1",
          name: "Wosk sojowy",
          sku,
        } as ProductOption
      }
      onChange={vi.fn()}
    />,
  );
}

describe("SelectedProductCard", () => {
  it("prints a SKU somebody chose", () => {
    renderCard("WAX-SOY-1KG");
    expect(screen.getByText("WAX-SOY-1KG")).toBeInTheDocument();
  });

  it("does not print the SKU the server minted", () => {
    renderCard("STM-CD4E8B75");
    expect(screen.getByText("Wosk sojowy")).toBeInTheDocument();
    expect(screen.queryByText("STM-CD4E8B75")).not.toBeInTheDocument();
  });
});
