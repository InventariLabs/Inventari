import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PartnerRequirementsSection } from "./PartnerRequirementsSection";

const fixtures = vi.hoisted(() => ({
  offer: {
    country: "FR" as string | null,
    require_partner_tax_id: true,
    rates: [],
  },
}));

vi.mock("@/modules/warehouse/hooks/useTaxRates", () => ({
  useCountryTaxRates: () => ({ data: fixtures.offer, isError: false }),
}));

const renderSection = (requireTaxId: boolean | null) => {
  const onChange = vi.fn();
  render(
    <PartnerRequirementsSection
      requireTaxId={requireTaxId}
      onRequireTaxIdChange={onChange}
      titleClassName=""
      descriptionClassName=""
    />,
  );
  return onChange;
};

const box = () =>
  screen.getByRole("checkbox", { name: /require partner tax id/i });

describe("PartnerRequirementsSection", () => {
  it("shows the country's requirement when the profile has no entry", () => {
    fixtures.offer = { country: "FR", require_partner_tax_id: true, rates: [] };
    renderSection(null);
    expect(box()).toBeChecked();
    expect(screen.getByTestId("tax-id-source")).toHaveTextContent(
      "Following the country (FR): a partner's tax ID is required",
    );
  });

  it("shows an unchecked box and says why when the country asks nothing", () => {
    fixtures.offer = {
      country: "DE",
      require_partner_tax_id: false,
      rates: [],
    };
    renderSection(null);
    expect(box()).not.toBeChecked();
    expect(screen.getByTestId("tax-id-source")).toHaveTextContent(
      "a partner's tax ID is not required",
    );
  });

  it("says no country is set instead of naming one", () => {
    fixtures.offer = {
      country: null,
      require_partner_tax_id: false,
      rates: [],
    };
    renderSection(null);
    expect(screen.getByTestId("tax-id-source")).toHaveTextContent(
      "No country is set",
    );
  });

  it("shows an explicit entry as the profile's own, against the country", async () => {
    fixtures.offer = { country: "FR", require_partner_tax_id: true, rates: [] };
    const onChange = renderSection(false);
    expect(box()).not.toBeChecked();
    expect(screen.getByTestId("tax-id-source")).toHaveTextContent(
      "Set for this profile",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Follow the country again" }),
    );
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("shows an explicit yes as checked and offers the way back", () => {
    fixtures.offer = {
      country: "DE",
      require_partner_tax_id: false,
      rates: [],
    };
    renderSection(true);
    expect(box()).toBeChecked();
    expect(
      screen.getByRole("button", { name: "Follow the country again" }),
    ).toBeInTheDocument();
  });

  it("turns an inherited rule into an explicit entry when ticked", async () => {
    fixtures.offer = {
      country: "DE",
      require_partner_tax_id: false,
      rates: [],
    };
    const onChange = renderSection(null);
    await userEvent.click(box());
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
