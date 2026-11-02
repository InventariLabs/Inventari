import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import PartnerImportModal from "./PartnerImportModal";

const analyzeImport = vi.fn();
const mutateAsync = vi.fn();

vi.mock("@/modules/partners/api/partners", () => ({
  partnersApi: { analyzeImport: (file: File) => analyzeImport(file) },
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  useImportPartners: () => ({ mutateAsync }),
}));

/**
 * Partners were the second thing a small company keeps in Excel and the
 * only one without a way in. A file with three good rows, a duplicate and a
 * broken row adds three partners, and the reader sees the two refused rows
 * with their reasons — not a count alone.
 */
describe("PartnerImportModal", () => {
  it("maps a partner sheet by its headers and reports every refused row", async () => {
    analyzeImport.mockResolvedValue({
      headers: ["Nazwa", "NIP", "Miasto"],
      preview_rows: [],
      total_rows: 0,
      filled_counts: {},
    });
    mutateAsync.mockResolvedValue({
      total: 5,
      imported: 3,
      failed: 2,
      errors: [
        {
          row: 5,
          error:
            'Duplicate partner: "Hurtownia ABC" already has this name or tax id',
        },
        { row: 6, error: "Missing partner name" },
      ],
    });
    render(<PartnerImportModal onClose={vi.fn()} />);

    const input = document.getElementById("import-file") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "partnerzy.xlsx")] },
    });
    await screen.findByText("partnerzy.xlsx");

    expect(screen.getByText(/Import only adds partners/)).toBeInTheDocument();
    expect(screen.getByText("Type for rows without one")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Process Import/ }));

    expect(await screen.findByText("Added 3 partners.")).toBeInTheDocument();
    expect(screen.getByText("#5:")).toBeInTheDocument();
    expect(
      screen.getByText(/already has this name or tax id/),
    ).toBeInTheDocument();
    expect(screen.getByText("#6:")).toBeInTheDocument();
    expect(screen.getByText("Missing partner name")).toBeInTheDocument();
    expect(mutateAsync).toHaveBeenCalledWith({
      file: expect.any(File),
      mapping: expect.objectContaining({
        name: "Nazwa",
        tax_id: "NIP",
        city: "Miasto",
      }),
      defaultType: "SUPPLIER",
    });
  });
});
