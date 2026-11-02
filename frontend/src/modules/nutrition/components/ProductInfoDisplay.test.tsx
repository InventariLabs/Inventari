import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProductInfoDisplay from "./ProductInfoDisplay";

const formData = {
  metadata: {
    off_enriched: true,
    nutrition: { energy_kcal: 539, proteins: 6.3 },
  },
};

describe("ProductInfoDisplay on the product form", () => {
  it("shows the panel before any category is chosen", () => {
    render(<ProductInfoDisplay data={{ formData }} />);
    expect(screen.getByText("539")).toBeInTheDocument();
  });

  it.each(["food", "cold_storage", "dry_goods"])(
    "shows the panel under a %s category",
    (categoryContextTag) => {
      render(<ProductInfoDisplay data={{ formData, categoryContextTag }} />);
      expect(screen.getByText("539")).toBeInTheDocument();
    },
  );

  it("shows nothing under an equipment category", () => {
    const { container } = render(
      <ProductInfoDisplay
        data={{ formData, categoryContextTag: "equipment" }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
