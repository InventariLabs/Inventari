import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import OpeningStockImportModal from "./OpeningStockImportModal";

const placesServed = vi.hoisted(() => ({
  main: { id: "loc-1", name: "Main warehouse" },
  back: { id: "loc-2", name: "Back room" },
}));
const analyzeImportSheet = vi.fn();
const mutateAsync = vi.fn();
const navigate = vi.fn();

vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  )),
  useNavigate: () => navigate,
}));

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: {
    analyzeImportSheet: (file: File) => analyzeImportSheet(file),
  },
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useImportOpeningStock: () => ({ mutateAsync }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useShowModuleData: () => true,
}));

/**
 * The moment a company leaves its spreadsheet is the moment it types its
 * whole stock into the app, one receipt line at a time. The sheet becomes
 * one draft receipt instead — once the reader has said where the goods
 * stand — and the refused rows come back with their reasons.
 */
describe("OpeningStockImportModal", () => {
  beforeEach(() => {
    serveLocations([placesServed.main, placesServed.back]);
  });

  async function reachMapping() {
    analyzeImportSheet.mockResolvedValue({
      headers: ["Produkt", "Stan", "Cena"],
      preview_rows: [{ Produkt: "Mąka", Stan: 10, Cena: "12.50" }],
      total_rows: 1,
    });
    render(<OpeningStockImportModal onClose={vi.fn()} />);
    const input = document.getElementById("import-file") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "stan.xlsx")] },
    });
    await screen.findByText("stan.xlsx");
  }

  it("says the locations could not be loaded instead of offering none", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    await reachMapping();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("will not run until the reader says where the goods stand", async () => {
    await reachMapping();
    const run = screen.getByRole("button", { name: /Process Import/ });
    expect(run).toBeDisabled();

    fireEvent.click(
      screen.getByRole("combobox", { name: /Where the goods stand/ }),
    );
    fireEvent.click(await screen.findByText("Main warehouse"));

    expect(run).toBeEnabled();
  });

  it("puts the only location there is into the field", async () => {
    // One place the goods may stand is no decision — the field says so as
    // soon as the list arrives, and the import it gates is open without a
    // click that would only confirm what is already on screen.
    serveLocations([placesServed.main]);
    await reachMapping();

    await waitFor(() =>
      expect(
        screen.getByRole("combobox", { name: /Where the goods stand/ }),
      ).toHaveTextContent("Main warehouse"),
    );
    expect(
      screen.getByRole("button", { name: /Process Import/ }),
    ).toBeEnabled();
  });

  it("hands the mapping and the location over and offers the draft", async () => {
    mutateAsync.mockResolvedValue({
      document_id: "doc-9",
      number: "IN/2026/009",
      total: 53,
      imported: 50,
      failed: 3,
      errors: [
        { row: 52, error: "Missing product name" },
        { row: 53, error: 'Column "Stan": cannot read "dużo" as a number' },
      ],
      matched: 50,
      unmatched: 0,
      stubs_created: 47,
    });
    await reachMapping();
    fireEvent.click(
      screen.getByRole("combobox", { name: /Where the goods stand/ }),
    );
    fireEvent.click(await screen.findByText("Main warehouse"));
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    expect(
      await screen.findByText("50 lines landed on the draft."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Draft IN\/2026\/009 is ready/),
    ).toBeInTheDocument();
    expect(screen.getByText("#52:")).toBeInTheDocument();
    expect(screen.getByText(/cannot read "dużo"/)).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith({
      file: expect.any(File),
      mapping: expect.objectContaining({
        name: "Produkt",
        quantity: "Stan",
        unit_price: "Cena",
      }),
      targetLocationId: "loc-1",
    });

    fireEvent.click(screen.getByRole("button", { name: /Open the draft/ }));
    expect(navigate).toHaveBeenCalledWith("/warehouse/documents/doc-9");
  });
});
