import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type {
  WarehouseDocument,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";
import { documentRow } from "@/test/factories/documents";
import DocumentHistoryPage from "./DocumentHistoryPage";

const useDocuments = vi.hoisted(() => vi.fn());
vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({ useDocuments }));

let valueTracking = false;
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: valueTracking },
  }),
}));

let canWrite = true;
vi.mock("@/hooks/useCanWrite", () => ({ useCanWrite: () => canWrite }));

// Which modules the organization has on; the registry itself is the real one.
const enabled = vi.hoisted(() => ({ modules: [] as string[] }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useEnabledModulesOptional: () => enabled.modules,
}));

moduleRegistry.register({
  name: "certs_demo",
  routes: [],
  documentColumnContributors: [
    {
      key: "certificate",
      label: "Certificate",
      hasValue: (d) => d.lines.some((l) => l.metaData.certs_demo?.number),
      render: (d) =>
        d.lines
          .map((l) => l.metaData.certs_demo?.number)
          .filter(Boolean)
          .join(", "),
    },
  ],
  documentFilterContributors: [{ key: "lapsing", label: "Lapsing soon" }],
});

const line = (name: string, quantity: string, symbol = "pcs") => ({
  id: `l-${name}`,
  name,
  quantity,
  done_quantity: quantity,
  uom: { id: "u", symbol, name: symbol, rounding: "1" },
});

// The list answers with rows; each is built from a document the way the
// server builds it, so a test still says what is on the document.
const doc = (overrides: Record<string, unknown>): WarehouseDocumentRow =>
  documentRow({
    id: "d1",
    number: "PZ/2026/014",
    type: "IN",
    status: "COMPLETED",
    created_at: "2026-10-19T08:00:00Z",
    completed_at: "2026-10-19T08:42:00Z",
    completed_by_name: "Anna",
    partner_snapshot: null,
    source_location_name: null,
    target_location_name: null,
    total_gross: null,
    currency: null,
    lines: [],
    ...overrides,
  } as unknown as WarehouseDocument);

const ENTRIES = [
  doc({
    id: "in",
    partner_snapshot: { name: "Mleczarnia Sady" },
    lines: [
      line("Gouda Cheese", "6"),
      line("Butter 200g", "4"),
      line("Plum Butter", "2"),
    ],
  }),
  doc({
    id: "move",
    number: "MM/2026/031",
    type: "INT",
    completed_by_name: "Marek",
    source_location_name: "Fridge A",
    target_location_name: "Fridge B",
    lines: [line("Gouda Cheese", "12")],
  }),
];

function answer(items: WarehouseDocumentRow[]) {
  useDocuments.mockReturnValue({
    data: { items, total: items.length },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
}

const lastParams = () => useDocuments.mock.calls.at(-1)?.[0];

describe("DocumentHistoryPage", () => {
  beforeEach(() => {
    useDocuments.mockReset();
    valueTracking = false;
    canWrite = true;
    enabled.modules = [];
    answer(ENTRIES);
  });

  it("asks only for completed documents, latest completed first", () => {
    // The row prints when a document was completed, so that is the order:
    // a dispatch written last week and completed today leads the list.
    renderWithProviders(<DocumentHistoryPage />);
    expect(lastParams()).toMatchObject({
      status: "COMPLETED",
      type: undefined,
      sort_by: "completed_at",
      sort_order: "desc",
    });
  });

  it("tells each entry as a sentence with its document number and type", () => {
    renderWithProviders(<DocumentHistoryPage />);
    expect(
      screen.getByText("Received 3 products from Mleczarnia Sady"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Gouda Cheese, Butter 200g and 1 other"),
    ).toBeInTheDocument();
    expect(screen.getByText("Moved 12 pcs. Gouda Cheese")).toBeInTheDocument();
    expect(screen.getByText("Fridge A → Fridge B")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PZ/2026/014" })).toHaveAttribute(
      "href",
      "/warehouse/documents/in",
    );
    expect(screen.getByText("Receipt")).toBeInTheDocument();
    expect(screen.getByText("Anna")).toBeInTheDocument();
  });

  it("names the amount a correction wrote, signed as its document shows it", () => {
    // "Corrected Packing tape 48mm" beside "Received 20 pcs." left the −8 to
    // the document alone.
    answer([
      doc({
        id: "fix",
        number: "KOR/2026/002",
        type: "CORRECTION",
        lines: [line("Packing tape 48mm", "-8")],
      }),
      doc({
        id: "fix-up",
        number: "KOR/2026/003",
        type: "CORRECTION",
        lines: [line("Stretch film", "3")],
      }),
    ]);
    renderWithProviders(<DocumentHistoryPage />);

    expect(
      screen.getByText("Corrected Packing tape 48mm by −8 pcs."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Corrected Stretch film by +3 pcs."),
    ).toBeInTheDocument();
  });

  it("shows the value only where value is tracked", () => {
    answer([
      doc({ total_gross: "1284.00", currency: "PLN", lines: [line("A", "1")] }),
    ]);
    const { unmount } = renderWithProviders(<DocumentHistoryPage />);
    expect(screen.queryByText(/1[\s,.]?284/)).not.toBeInTheDocument();
    unmount();

    valueTracking = true;
    renderWithProviders(<DocumentHistoryPage />);
    expect(screen.getByText(/1[\s,.]?284/)).toBeInTheDocument();
  });

  it("quotes no amount for a transfer, whatever the profile tracks", () => {
    valueTracking = true;
    answer([
      doc({
        type: "INT",
        number: "MM/2026/031",
        total_gross: "1284.00",
        currency: "PLN",
        lines: [line("A", "1")],
      }),
    ]);

    renderWithProviders(<DocumentHistoryPage />);

    expect(screen.queryByText(/1[\s,.]?284/)).not.toBeInTheDocument();
  });

  it("narrows by the kind of action", async () => {
    renderWithProviders(<DocumentHistoryPage />);
    await userEvent.click(screen.getByRole("tab", { name: "Receipts" }));
    expect(lastParams()).toMatchObject({ type: "IN,INTERNAL_IN" });
    await userEvent.click(screen.getByRole("tab", { name: "Corrections" }));
    expect(lastParams()).toMatchObject({ type: "CORRECTION,ADJUSTMENT" });
  });

  it("searches products, partners and numbers through the list search", async () => {
    renderWithProviders(<DocumentHistoryPage />);
    await userEvent.type(screen.getByRole("textbox"), "gouda");
    expect(lastParams()).toMatchObject({ search: "gouda" });
  });

  it("keeps drafts and planned documents behind their own filter", async () => {
    answer([
      doc({
        id: "draft",
        number: "PZ/2026/015",
        status: "DRAFT",
        completed_at: null,
        partner_snapshot: { name: "Mleczarnia Sady" },
        lines: [line("Gouda Cheese", "6")],
      }),
    ]);
    renderWithProviders(<DocumentHistoryPage />);
    await userEvent.click(
      screen.getByRole("button", { name: "Drafts and planned" }),
    );
    // Work not done yet shows when it was typed in, and is ordered by it.
    expect(lastParams()).toMatchObject({
      status: "DRAFT,PENDING_APPROVAL,CONFIRMED",
      sort_by: "created_at",
    });
    // A draft is not told as if it had happened.
    expect(screen.queryByText(/^Received/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Receipt: 6 pcs. Gouda Cheese"),
    ).toBeInTheDocument();
  });

  describe("what a module adds", () => {
    const certified = () =>
      answer([
        doc({
          id: "in",
          lines: [
            { ...line("Gouda Cheese", "6"), meta_data: {} },
            {
              ...line("Butter 200g", "4"),
              meta_data: { certs_demo: { number: "C-17" } },
            },
          ],
        }),
        doc({ id: "move", number: "MM/2026/031", type: "INT" }),
      ]);

    it("shows a module's column, named, on the rows it fills", () => {
      enabled.modules = ["certs_demo"];
      certified();
      renderWithProviders(<DocumentHistoryPage />);

      expect(screen.getByText("C-17")).toBeInTheDocument();
      // The list has no header row: one name per filled cell.
      expect(screen.getAllByText("Certificate")).toHaveLength(1);
    });

    it("leaves the column out when no row on the page fills it", () => {
      enabled.modules = ["certs_demo"];
      renderWithProviders(<DocumentHistoryPage />);

      expect(screen.queryByText("Certificate")).not.toBeInTheDocument();
      // Nor does the row keep an empty track for it.
      for (const row of screen.getAllByRole("listitem")) {
        expect(row).not.toHaveAttribute("style");
      }
    });

    it("narrows the list on the server with a module's chip", async () => {
      enabled.modules = ["certs_demo"];
      renderWithProviders(<DocumentHistoryPage />);
      expect(lastParams().module_filter).toBeUndefined();

      await userEvent.click(
        screen.getByRole("button", { name: "Lapsing soon" }),
      );
      expect(lastParams()).toMatchObject({
        module_filter: ["certs_demo:lapsing"],
      });

      await userEvent.click(
        screen.getByRole("button", { name: "Lapsing soon" }),
      );
      expect(lastParams().module_filter).toBeUndefined();
    });

    it("adds nothing while the module is switched off", () => {
      certified();
      renderWithProviders(<DocumentHistoryPage />);

      expect(screen.queryByText("C-17")).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Lapsing soon" }),
      ).not.toBeInTheDocument();
    });
  });

  it("offers the register, the month close and a manual document", () => {
    renderWithProviders(<DocumentHistoryPage />);
    const panel = screen.getByRole("complementary", { name: "For the office" });
    expect(
      within(panel).getByRole("link", { name: /^Documents/ }),
    ).toHaveAttribute("href", "/warehouse/all");
    expect(
      within(panel).getByRole("link", { name: /Document register/ }),
    ).toHaveAttribute("href", "/warehouse/register");
    expect(
      within(panel).getByRole("link", { name: /Close month/ }),
    ).toHaveAttribute("href", "/warehouse/periods");
    const manual = within(panel).getByRole("button", {
      name: /New document manually/,
    });
    // The description names every type the menu under it offers, from the
    // menu's own labels: the hand-kept list promised five and the menu made
    // six, so the write-off read as an offer the panel never mentioned.
    expect(manual).toHaveTextContent(
      "Receipt, Delivery, Transfer, Internal Receipt, Internal Issue, Scrap",
    );
  });

  it("does not offer a manual document to a read-only account", () => {
    canWrite = false;
    renderWithProviders(<DocumentHistoryPage />);
    expect(
      screen.queryByRole("button", { name: /New document manually/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Document register/ }),
    ).toBeInTheDocument();
  });

  it("says so when nothing matches the search", async () => {
    answer([]);
    renderWithProviders(<DocumentHistoryPage />);
    expect(screen.getByText("Nothing has moved yet")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "zzz");
    expect(
      screen.getByText("No documents match the filter"),
    ).toBeInTheDocument();
  });
});
