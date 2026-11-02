import { describe, expect, it, vi } from "vitest";
import { formatDate } from "@/utils/formatters";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { PartnerDetailSheet } from "./PartnerDetailSheet";
import type { Partner } from "@/types";

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartner: () => ({ data: undefined }),
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/contexts/ModulesContext")>();
  return {
    ...actual,
    // The related links render only where their module is on; both link
    // targets are enabled here so the counts can be asserted.
    useModules: () => ({
      isModuleEnabled: (m: string) =>
        m === "warehouse" || m === "purchase_orders",
    }),
  };
});

const makePartner = (overrides: Partial<Partner> = {}): Partner => ({
  id: "p1",
  organization_id: "org-1",
  name: "ABC Wholesaler",
  document_count: 0,
  purchase_order_count: 0,
  code: "SUP-001",
  type: "SUPPLIER",
  tax_id: "PL1234567890",
  is_consumer: false,
  email: "contact@abc.com",
  phone: "+48 123 456 789",
  website: "https://abc.com",
  contact_person: "Jane Smith",
  address: {
    street: "Main St 1",
    postal_code: "00-001",
    city: "Warsaw",
    country: "PL",
  },
  notes: "Preferred supplier",
  is_active: true,
  created_by: null,
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
  ...overrides,
});

const makeProps = (overrides: Partial<Partner> = {}) => ({
  partner: makePartner(overrides),
  onClose: vi.fn(),
  onEdit: vi.fn(),
  onToggleActive: vi.fn(),
});

describe("PartnerDetailSheet", () => {
  it("renders name, type, code and tax ID", () => {
    const props = makeProps();
    render(<PartnerDetailSheet {...props} />);
    expect(screen.getByText("ABC Wholesaler")).toBeInTheDocument();
    expect(screen.getByText("Supplier")).toBeInTheDocument();
    expect(screen.getByText("SUP-001")).toBeInTheDocument();
    expect(screen.getByText("PL1234567890")).toBeInTheDocument();
  });

  it("says when the partner is a private person, and only then", () => {
    const { unmount } = render(
      <PartnerDetailSheet {...makeProps({ is_consumer: true })} />,
    );
    expect(screen.getByText("Private person (consumer)")).toBeInTheDocument();
    unmount();

    render(<PartnerDetailSheet {...makeProps()} />);
    expect(
      screen.queryByText("Private person (consumer)"),
    ).not.toBeInTheDocument();
  });

  it("renders mailto and tel links", () => {
    const props = makeProps();
    render(<PartnerDetailSheet {...props} />);
    const mail = screen.getByRole("link", { name: /contact@abc\.com/ });
    expect(mail).toHaveAttribute("href", "mailto:contact@abc.com");
    const phone = screen.getByRole("link", { name: /\+48 123 456 789/ });
    expect(phone).toHaveAttribute("href", "tel:+48 123 456 789");
  });

  it("renders website link with https scheme when protocol missing", () => {
    const props = makeProps({ website: "abc.example.com" });
    render(<PartnerDetailSheet {...props} />);
    expect(
      screen.getByRole("link", { name: /abc\.example\.com/ }),
    ).toHaveAttribute("href", "https://abc.example.com");
  });

  it("renders contact person and address", () => {
    const props = makeProps();
    render(<PartnerDetailSheet {...props} />);
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(
      screen.getByText(/Main St 1, 00-001, Warsaw, Poland/),
    ).toBeInTheDocument();
  });

  it("does not render rows for missing fields", () => {
    const props = makeProps({
      code: null,
      email: null,
      phone: null,
      website: null,
      contact_person: null,
      address: null,
      notes: null,
    });
    render(<PartnerDetailSheet {...props} />);
    expect(screen.queryByText("SUP-001")).not.toBeInTheDocument();
    expect(screen.queryByText("Jane Smith")).not.toBeInTheDocument();
  });

  it("shows inactive status badge when partner is inactive", () => {
    const props = makeProps({ is_active: false });
    render(<PartnerDetailSheet {...props} />);
    expect(screen.getByText("Inactive")).toBeInTheDocument();
  });

  it("calls onEdit from the Edit button", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(<PartnerDetailSheet {...props} />);
    await user.click(screen.getByRole("button", { name: /edit/i }));
    expect(props.onEdit).toHaveBeenCalledWith(props.partner);
  });

  it("calls onToggleActive from the deactivate button", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(<PartnerDetailSheet {...props} />);
    await user.click(screen.getByRole("button", { name: /deactivate/i }));
    expect(props.onToggleActive).toHaveBeenCalledWith(props.partner);
  });

  it("calls onClose from the close button", async () => {
    const props = makeProps();
    const user = userEvent.setup();
    render(<PartnerDetailSheet {...props} />);
    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(props.onClose).toHaveBeenCalled();
  });

  it("shows the document stats the list row already shows", () => {
    const props = makeProps({
      document_count: 2,
      total_amount: null,
      last_activity_at: "2026-07-02T10:00:00Z",
    });
    render(<PartnerDetailSheet {...props} />);
    expect(screen.getByText("2 documents")).toBeInTheDocument();
    expect(screen.getByText("Multiple currencies")).toBeInTheDocument();
    expect(screen.getByText(/Last activity/)).toBeInTheDocument();
    // The shared formatter, like every other date in the app — the bare
    // toLocaleDateString this replaced printed "7/2/2026" in English.
    expect(
      screen.getByText(formatDate("2026-07-02T10:00:00Z")),
    ).toBeInTheDocument();
  });

  it("counts the purchase orders behind the related link, like the documents link", () => {
    // The orders link carried a hard "not counted" where the documents link
    // showed its number, so the reader could not tell zero from unknown.
    render(
      <PartnerDetailSheet
        {...makeProps({ document_count: 2, purchase_order_count: 3 })}
      />,
    );

    const ordersLink = screen.getByRole("link", { name: /purchase orders/i });
    expect(ordersLink).toHaveAttribute(
      "href",
      "/purchase-orders?partner_id=p1",
    );
    expect(ordersLink).toHaveTextContent("3");
    expect(
      screen.getByRole("link", { name: /warehouse documents/i }),
    ).toHaveTextContent("2");
  });

  it("states a counted zero for a partner with no purchase orders", () => {
    render(<PartnerDetailSheet {...makeProps({ purchase_order_count: 0 })} />);

    const ordersLink = screen.getByRole("link", { name: /purchase orders/i });
    expect(ordersLink).toHaveTextContent("0");
  });

  it("renders a single-currency turnover without claiming a currency", () => {
    const props = makeProps({
      document_count: 1,
      total_amount: "120.50",
      last_activity_at: "2026-07-01T10:00:00Z",
    });
    render(<PartnerDetailSheet {...props} />);
    // formatMoney with no currency appends a bare number with a "?" marker.
    expect(screen.getByText(/120\.50/)).toBeInTheDocument();
  });

  it("shows no turnover for a partner whose documents carry no value", () => {
    // The API answers a total of zero with no currency; formatMoney would
    // print that as "0.00 ?", which reads as an unknown amount.
    render(
      <PartnerDetailSheet
        {...makeProps({
          document_count: 3,
          total_amount: "0",
          turnover_currency: null,
        })}
      />,
    );
    expect(screen.queryByText(/0\.00/)).not.toBeInTheDocument();
    expect(screen.queryByText("Multiple currencies")).not.toBeInTheDocument();
    expect(screen.getByText(/Turnover/)).toHaveTextContent("Turnover: —");
  });
});
