import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PartnerRequirementsSection } from "./PartnerRequirementsSection";

const fixtures = vi.hoisted(() => ({
  offer: {
    country: "FR" as string | null,
    require_partner_tax_id: true,
    rates: [],
  } as
    | {
        country: string | null;
        require_partner_tax_id: boolean;
        rates: never[];
      }
    | undefined,
  isError: false,
}));

vi.mock("@/modules/warehouse/hooks/useTaxRates", () => ({
  useCountryTaxRates: () => ({
    data: fixtures.offer,
    isError: fixtures.isError,
  }),
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
  beforeEach(() => {
    fixtures.isError = false;
  });

  it("does not claim there is no country while the offer is loading", () => {
    fixtures.offer = undefined;
    renderSection(null);
    const source = screen.getByTestId("tax-id-source");
    expect(source).toHaveTextContent("could not be read yet");
    expect(source).not.toHaveTextContent("No country is set");
  });

  it("does not claim there is no country when the offer failed", () => {
    fixtures.offer = undefined;
    fixtures.isError = true;
    renderSection(null);
    expect(screen.getByTestId("tax-id-source")).not.toHaveTextContent(
      "No country is set",
    );
  });

  it("ties the sentence naming the source to the checkbox", () => {
    fixtures.offer = { country: "FR", require_partner_tax_id: true, rates: [] };
    renderSection(null);
    expect(box()).toHaveAccessibleDescription(
      expect.stringContaining("Following the country (FR)"),
    );
  });

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
