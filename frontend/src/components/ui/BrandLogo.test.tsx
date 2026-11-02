import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { BrandLogo } from "./BrandLogo";

describe("BrandLogo", () => {
  it("renders the plain Inventari wordmark without a subtitle key", () => {
    render(<BrandLogo />);
    expect(screen.getByText("Inventari")).toBeInTheDocument();
    // No subtitle for unbranded profiles / auth pages.
    expect(screen.queryByText(/for Home|for Business/)).not.toBeInTheDocument();
  });

  it("renders the per-profile subtitle resolved through i18n", () => {
    render(<BrandLogo subtitleKey="profiles.food_home.subtitle" />);
    expect(screen.getByText("Inventari")).toBeInTheDocument();
    expect(screen.getByText("for Home")).toBeInTheDocument();
  });

  it("renders the equipment profile subtitle", () => {
    render(<BrandLogo subtitleKey="profiles.equipment_wms.subtitle" />);
    expect(screen.getByText("for Business")).toBeInTheDocument();
  });

  it("treats a null subtitle key as unbranded", () => {
    render(<BrandLogo subtitleKey={null} />);
    expect(screen.getByText("Inventari")).toBeInTheDocument();
    expect(screen.queryByText(/for Home|for Business/)).not.toBeInTheDocument();
  });

  it("takes the brand-text token, so it reads under every profile in dark", () => {
    // text-primary-500 is the profile's own 500 in dark: 4.05:1 on a card
    // under the blue palette. The token carries a lighter step there.
    render(<BrandLogo subtitleKey={null} />);
    const root = screen.getByText("Inventari").parentElement?.parentElement;
    const classes = root?.className ?? "";
    expect(classes).toContain("text-on-primary");
    expect(classes).not.toContain("dark:text-primary-500");
  });
});
