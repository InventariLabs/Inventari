import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { PartnerList } from "./PartnerList";
import type { Partner } from "@/types";

const partner = {
  id: "p-1",
  name: "Acme Foods",
  type: "SUPPLIER",
  tax_id: "PL123",
  email: "a@acme.test",
  phone: null,
  contact_person: "Ann",
  is_active: true,
  document_count: 4,
  total_amount: "120.5",
  turnover_currency: "EUR",
  last_activity_at: null,
} as unknown as Partner;

const handlers = {
  canWrite: true,
  onOpen: vi.fn(),
  onEdit: vi.fn(),
  onToggleActive: vi.fn(),
};

describe("PartnerList", () => {
  it("is a table with a header over every column", () => {
    render(<PartnerList partners={[partner]} {...handlers} />);

    expect(
      screen.getAllByRole("columnheader").map((th) => th.textContent),
    ).toEqual([
      "Name",
      "Type",
      "Tax ID",
      "Contact",
      "Documents",
      "Turnover",
      "Last activity",
      "Actions",
    ]);
    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("Acme Foods")).toBeInTheDocument();
    expect(within(row).getByText("PL123")).toBeInTheDocument();
    expect(within(row).getByText("a@acme.test")).toBeInTheDocument();
  });

  it("shows no turnover for a partner whose documents carry no value", () => {
    const valueless = {
      ...partner,
      total_amount: "0",
      turnover_currency: null,
    } as unknown as Partner;
    render(<PartnerList partners={[valueless]} {...handlers} />);

    const row = screen.getAllByRole("row")[1];
    expect(within(row).queryByText(/0\.00/)).not.toBeInTheDocument();
    // Name, Type, Tax ID, Contact, Documents, Turnover — the sixth cell.
    expect(within(row).getAllByRole("cell")[5]).toHaveTextContent("—");
  });

  it("keeps Deactivate apart from Edit and in the danger colour", () => {
    const { container } = render(
      <PartnerList partners={[partner]} {...handlers} />,
    );
    expect(container.querySelector('[aria-hidden="true"].w-px')).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Deactivate" }).className,
    ).toContain("text-on-danger");
  });

  it("opens the partner from its row but not from an action", async () => {
    const onOpen = vi.fn();
    const onEdit = vi.fn();
    render(
      <PartnerList
        partners={[partner]}
        {...handlers}
        onOpen={onOpen}
        onEdit={onEdit}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith(partner);
    expect(onOpen).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText("Acme Foods"));
    expect(onOpen).toHaveBeenCalledWith(partner);
  });
});

describe("PartnerList on a phone", () => {
  const original = window.matchMedia;
  afterEach(() => {
    window.matchMedia = original;
  });

  it("keeps the card stack, with no table", () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    render(<PartnerList partners={[partner]} {...handlers} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Acme Foods" }),
    ).toBeInTheDocument();
  });
});
