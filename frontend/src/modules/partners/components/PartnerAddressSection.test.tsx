import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { PartnerAddressSection } from "./PartnerAddressSection";

describe("PartnerAddressSection country select", () => {
  it("shows a legacy value outside the curated list as 'Other: <value>'", () => {
    render(
      <PartnerAddressSection
        address={{ country: "ZZ" }}
        open
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );
    // "ZZ" is not one of the curated 40 codes, so the select offers it as a
    // preserved legacy "Other: ZZ" option rather than silently dropping it.
    expect(screen.getByText("Other: ZZ")).toBeInTheDocument();
  });

  it("calls onChange with the selected country code", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PartnerAddressSection
        address={{ country: "" }}
        open
        onToggle={vi.fn()}
        onChange={onChange}
      />,
    );

    const select = screen.getByLabelText(/Country/i);
    await user.selectOptions(select, "PL");
    expect(onChange).toHaveBeenCalledWith("country", "PL");
  });
});
