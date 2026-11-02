import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import { toast } from "sonner";
import i18n from "@/i18n/config";
import { queryKeys } from "@/hooks/queries/keys";
import { useAuthStore } from "@/store/authStore";
import type { User } from "@/types";
import { DocumentImportModal, guessMapping } from "./DocumentImportModal";

const post = vi.fn();
vi.mock("@/lib/api/client", () => ({
  api: { post: (...a: unknown[]) => post(...a) },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));

/** The mapping grid is a Radix Select per field; what this spec needs from it
 *  is one mapped column, so it says so directly. */
vi.mock("./ColumnMappingForm", () => ({
  ColumnMappingForm: ({
    onChange,
  }: {
    onChange: (field: string, value: string) => void;
  }) => (
    <button type="button" onClick={() => onChange("name", "nazwa")}>
      map name
    </button>
  ),
}));

const DOC_ID = "11111111-1111-1111-1111-111111111111";

type Target =
  { documentId: string } | { documentType: string; sourceLocationId?: string };

function renderModal(
  onImported = vi.fn(),
  target: Target = { documentId: DOC_ID },
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <I18nextProvider i18n={i18n}>
        <DocumentImportModal
          {...target}
          onClose={vi.fn()}
          onImported={onImported}
        />
      </I18nextProvider>
    </QueryClientProvider>,
  );
  return { invalidate, onImported };
}

async function reachMapping() {
  post.mockResolvedValueOnce({
    data: {
      headers: ["nazwa", "ilosc"],
      preview_rows: [{ nazwa: "Mąka", ilosc: 2 }],
      total_rows: 1,
    },
  });
  const input = document.getElementById(
    "document-import-file-input",
  ) as HTMLInputElement;
  fireEvent.change(input, {
    target: { files: [new File(["x"], "linie.csv")] },
  });
  await screen.findByRole("button", { name: "map name" });
  fireEvent.click(screen.getByRole("button", { name: "map name" }));
}

const DOCSTUBS_USER: User = {
  permissions: [],
  id: "u1",
  email: "docstubs@example.com",
  full_name: "Documents Only",
  role: "user",
  is_superuser: false,
  is_active: true,
  is_blocked: false,
  preferred_language: "en",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("DocumentImportModal", () => {
  beforeEach(() => {
    post.mockReset();
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.warning).mockClear();
    vi.mocked(toast.error).mockClear();
  });

  afterEach(() => {
    useAuthStore.setState({ user: null, isAuthenticated: false });
  });

  it("re-reads the document it just wrote to", async () => {
    // The import is a write through an endpoint of its own. Nothing
    // invalidated the document, so the card behind this sheet went on saying
    // "1 line · plan 5" over a document that had three, until a reload.
    const { invalidate, onImported } = renderModal();
    await reachMapping();

    post.mockResolvedValueOnce({
      data: {
        imported: 3,
        matched: 1,
        unmatched: 2,
        stubs_created: 0,
        failed: 0,
        errors: [],
        no_stock: [],
        lines: [],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import/i }));

    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: queryKeys.documents.detail(DOC_ID),
      });
    });
    expect(onImported).toHaveBeenCalled();
  });

  it("imports a sheet whose only product column is a code", async () => {
    // "code,quantity" maps the code to SKU and leaves Name empty; the backend
    // finds the product by SKU, so Import must not insist on a Name column.
    renderModal();
    post.mockResolvedValueOnce({
      data: {
        headers: ["code", "quantity"],
        preview_rows: [{ code: "FLOUR-550", quantity: 2 }],
        total_rows: 1,
      },
    });
    const input = document.getElementById(
      "document-import-file-input",
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "linie.csv")] },
    });
    await screen.findByRole("button", { name: "map name" });

    post.mockResolvedValueOnce({
      data: {
        imported: 1,
        matched: 1,
        unmatched: 0,
        stubs_created: 0,
        failed: 0,
        errors: [],
        no_stock: [],
        lines: [],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import/i }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(toast.error).not.toHaveBeenCalled();
    const body = post.mock.calls[1][1] as FormData;
    expect(JSON.parse(body.get("mapping_json") as string)).toMatchObject({
      name: "",
      sku: "code",
    });
  });

  it("says what was matched and what was not when rows are left behind", async () => {
    // "Imported 3 lines" over a sheet where two rows never reached a product
    // reads as success. The toast names both counts so nobody posts a
    // delivery missing rows they never heard about.
    renderModal();
    await reachMapping();

    post.mockResolvedValueOnce({
      data: {
        imported: 3,
        matched: 1,
        unmatched: 2,
        stubs_created: 0,
        failed: 0,
        errors: [],
        no_stock: [],
        lines: [],
      },
    });
    fireEvent.click(screen.getByRole("button", { name: /Import/i }));

    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith("1 matched · 2 unmatched"),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("reads the rows for a document not saved yet and hands the lines back", async () => {
    // The create form had no import: there was no draft to write into. The
    // rows are read for the type and shelf being written, and nothing is
    // written to any document.
    const onImported = vi.fn();
    const { invalidate } = renderModal(onImported, {
      documentType: "OUT",
      sourceLocationId: "shelf-1",
    });
    await reachMapping();

    const result = {
      imported: 1,
      matched: 1,
      unmatched: 0,
      stubs_created: 0,
      failed: 0,
      errors: [],
      no_stock: [],
      lines: [{ id: "l1", name: "Mąka", quantity: "2", item_id: "rec-1" }],
    };
    post.mockResolvedValueOnce({ data: result });
    fireEvent.click(screen.getByRole("button", { name: /Import/i }));

    await waitFor(() => expect(onImported).toHaveBeenCalledWith(result));
    const [url, body] = post.mock.calls[1] as [string, FormData];
    expect(url).toBe("/warehouse/import/lines");
    expect(body.get("type")).toBe("OUT");
    expect(body.get("source_location_id")).toBe("shelf-1");
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("does not re-read the document when the import failed", async () => {
    const { invalidate, onImported } = renderModal();
    await reachMapping();

    post.mockRejectedValueOnce(new Error("nope"));
    fireEvent.click(screen.getByRole("button", { name: /Import/i }));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(onImported).not.toHaveBeenCalled();
    expect(invalidate).not.toHaveBeenCalledWith({
      queryKey: queryKeys.documents.detail(DOC_ID),
    });
  });

  it("hides the stub offer from an account without items:write", async () => {
    // Founding templates is items:write work; the modal does not offer a
    // checkbox the backend would refuse.
    useAuthStore.setState({
      user: {
        ...DOCSTUBS_USER,
        permissions: ["warehouse:read", "warehouse:write"],
      },
      isAuthenticated: true,
    });
    renderModal();
    await reachMapping();

    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("offers the stubs to an account holding items:write", async () => {
    useAuthStore.setState({
      user: {
        ...DOCSTUBS_USER,
        permissions: ["warehouse:read", "warehouse:write", "items:write"],
      },
      isAuthenticated: true,
    });
    renderModal();
    await reachMapping();

    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("keeps the file and paste panels in one grid cell, so the sheet does not jump between them", () => {
    renderModal();
    // The paste tab was 120px taller than the file tab; each in turn used to
    // size the sheet, which moved on every switch.
    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    expect(panels).toHaveLength(2);
    for (const panel of panels) {
      expect(panel.className).toContain("col-start-1");
      expect(panel.parentElement?.className).toContain("grid");
    }
  });
});

describe("guessMapping", () => {
  it("maps the headers a pasted sheet usually carries", () => {
    expect(
      guessMapping(["name", "quantity", "barcode", "batch", "expiry date"]),
    ).toEqual({
      name: "name",
      quantity: "quantity",
      barcode: "barcode",
      sku: "",
      uom_symbol: "",
      unit_price: "",
      tax_rate: "",
      batch_number: "batch",
      expiry_date: "expiry date",
      brand: "",
    });
  });

  it("folds accents and accepts Polish header names", () => {
    const mapping = guessMapping(["Nazwa", "Ilość", "Data ważności"]);
    expect(mapping.name).toBe("Nazwa");
    expect(mapping.quantity).toBe("Ilość");
    expect(mapping.expiry_date).toBe("Data ważności");
  });

  it("leaves a header it does not know unmapped", () => {
    const mapping = guessMapping(["name", "quantity", "magic column"]);
    expect(Object.values(mapping)).not.toContain("magic column");
  });

  it("never maps one column to two fields", () => {
    // "code" is an SKU alias and nothing else; a sheet with "code" and "sku"
    // gives the one column to SKU and leaves the other unmatched.
    const mapping = guessMapping(["name", "code", "sku"]);
    expect([mapping.sku]).toContain("code");
    expect(
      Object.values(mapping).filter((value) => value === "code"),
    ).toHaveLength(1);
  });
});
