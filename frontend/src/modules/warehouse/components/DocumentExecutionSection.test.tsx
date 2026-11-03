import { describe, expect, it } from "vitest";
import { render, screen, within } from "@/test/utils";
import { DocumentExecutionSection } from "./DocumentExecutionSection";
import type {
  DocumentLine,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import { documentLine, warehouseDocument } from "@/test/factories/documents";

function line(overrides: Partial<DocumentLine> = {}): DocumentLine {
  return documentLine({
    id: "line-1",
    document_id: "doc-1",
    item_id: null,
    product_template_id: null,
    name: "Makaron bez karty",
    brand: null,
    barcode: null,
    quantity: "5",
    expected_quantity: "5",
    done_quantity: "0",
    uom_id: null,
    uom: null,
    batch_number: null,
    expiry_date: null,
    notes: null,
    line_number: 1,
    ...overrides,
  });
}

function document_(
  lines: DocumentLine[],
  status: WarehouseDocument["status"] = "CONFIRMED",
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "IN/2026/005",
    status,
    partner_id: null,
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines,
    created_by: "user-1",
    confirmed_by: "user-1",
    created_at: "2026-09-20T10:00:00Z",
    updated_at: "2026-09-20T10:00:00Z",
    confirmed_at: "2026-09-20T10:00:00Z",
    completed_at: status === "COMPLETED" ? "2026-09-20T12:00:00Z" : null,
    ...overrides,
  });
}

function correction_(
  lines: DocumentLine[],
  correctsDocumentType: string,
  status: WarehouseDocument["status"] = "CONFIRMED",
): WarehouseDocument {
  return document_(lines, status, {
    type: "CORRECTION",
    corrects_document_id: "original-1",
    corrects_document_type: correctsDocumentType,
  });
}

/** The figure a snapshot tile prints, found by the label it carries. */
function snapshotValue(label: string): string {
  const tile = within(screen.getByTestId("document-operational-snapshot"))
    .getByText(label)
    .closest("div.rounded-xl");
  return tile?.lastElementChild?.textContent ?? "";
}

describe("DocumentExecutionSection — the summary names what it counted", () => {
  it("counts the quantities without claiming they are pieces", () => {
    // The second pair sums quantities across lines, and those lines need not
    // share a unit — a hand-typed line carries none at all. "Sztuki 0/5"
    // named pieces the document had never been told to count, and the same
    // word appeared for a document measured in kilograms.
    render(
      <DocumentExecutionSection
        document={document_([line()])}
        isCorrection={false}
      />,
    );

    expect(
      screen.getByText("Lines 0/1 done · quantity 0/5"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Units 0\/5/)).toBeNull();
  });

  it("stops asking a booked document to be closed", () => {
    // A COMPLETED document's remaining actions are "Download PDF" and
    // "Duplicate" — there is nothing left to click, yet the section kept
    // announcing every line "ready to close", because its execution phase
    // covered COMPLETED as well as CONFIRMED. The reader went looking for
    // a close button the screen did not carry, and since the same
    // sentence is the real instruction on a confirmed document, it
    // stopped signalling anything at all.
    render(
      <DocumentExecutionSection
        document={document_([line({ done_quantity: "5" })], "COMPLETED")}
        isCorrection={false}
      />,
    );

    expect(screen.queryByText(/ready to close/i)).not.toBeInTheDocument();
  });

  it("still names the closing step on a confirmed document", () => {
    render(
      <DocumentExecutionSection
        document={document_([line({ done_quantity: "5" })], "CONFIRMED")}
        isCorrection={false}
      />,
    );

    expect(screen.getByText(/ready to close/i)).toBeInTheDocument();
  });

  it("shows the quantity per unit instead of one cross-unit sum", () => {
    // 20 pcs + 12.5 kg + 30 pack read "Quantity 56.5/62.5" — with a bar whose
    // denominator was the same invented number. The summary keeps one
    // figure per unit and drops a bar that has no common measure.
    const { container } = render(
      <DocumentExecutionSection
        document={document_([
          line({
            id: "l1",
            expected_quantity: "20",
            quantity: "20",
            done_quantity: "18",
            uom: { id: "u1", symbol: "pcs", name: "pieces", rounding: "1" },
          }),
          line({
            id: "l2",
            expected_quantity: "12.5",
            quantity: "12.5",
            done_quantity: "12.5",
            uom: { id: "u2", symbol: "kg", name: "kilograms", rounding: "1" },
          }),
          line({
            id: "l3",
            expected_quantity: "30",
            quantity: "30",
            done_quantity: "26",
            uom: { id: "u3", symbol: "pack", name: "packs", rounding: "1" },
          }),
        ])}
        isCorrection={false}
      />,
    );

    expect(screen.queryByText(/56\.5\/62\.5/)).toBeNull();
    expect(
      screen.getByText(
        "Lines 1/3 done · quantity 18/20 pcs. · 12.5/12.5 kg · 26/30 pack",
      ),
    ).toBeInTheDocument();
    expect(container.querySelector(".bg-accent-600")).toBeNull();
  });

  it("keeps the snapshot of a draft per unit as well", () => {
    const { container } = render(
      <DocumentExecutionSection
        document={document_(
          [
            line({
              id: "l1",
              expected_quantity: "20",
              quantity: "20",
              uom: { id: "u1", symbol: "pcs", name: "pieces", rounding: "1" },
            }),
            line({
              id: "l2",
              expected_quantity: "12.5",
              quantity: "12.5",
              uom: { id: "u2", symbol: "kg", name: "kilograms", rounding: "1" },
            }),
            line({
              id: "l3",
              expected_quantity: "30",
              quantity: "30",
              uom: { id: "u3", symbol: "pack", name: "packs", rounding: "1" },
            }),
          ],
          "DRAFT",
        )}
        isCorrection={false}
      />,
    );

    expect(screen.queryByText("62.5")).toBeNull();
    expect(screen.getByText("20 pcs. · 12.5 kg · 30 pack")).toBeInTheDocument();
    expect(
      screen.getByText("Done: 0/20 pcs. · 0/12.5 kg · 0/30 pack"),
    ).toBeInTheDocument();
    expect(container.querySelector(".bg-accent-600")).toBeNull();
  });
});

describe("DocumentExecutionSection — a correction reads the direction stock moved", () => {
  it("shows a scrap correction's minus delta as goods added", () => {
    // A scrap takes goods off the shelf, so a correction of one turns its
    // delta round: the executor applies delta × correction_sign(SCRAP), and
    // −1 puts a unit back. The summary read the delta's own sign and said
    // "Removed 1" over a shelf that had just received one.
    render(
      <DocumentExecutionSection
        document={correction_(
          [line({ quantity: "-1", expected_quantity: "-1" })],
          "SCRAP",
        )}
        isCorrection
      />,
    );

    expect(screen.getByText("Correction: +1 / −0")).toBeInTheDocument();
    expect(snapshotValue("Added")).toBe("1");
    expect(snapshotValue("Removed")).toBe("0");
  });

  it("shows a scrap correction's plus delta as goods removed", () => {
    render(
      <DocumentExecutionSection
        document={correction_(
          [line({ quantity: "1", expected_quantity: "1" })],
          "SCRAP",
        )}
        isCorrection
      />,
    );

    expect(screen.getByText("Correction: +0 / −1")).toBeInTheDocument();
    expect(snapshotValue("Added")).toBe("0");
    expect(snapshotValue("Removed")).toBe("1");
  });

  it("keeps a receipt correction's minus delta as goods removed", () => {
    // A receipt brings goods in, so its correction needs no turning round:
    // the delta is already the direction stock moves.
    render(
      <DocumentExecutionSection
        document={correction_(
          [line({ quantity: "-2", expected_quantity: "-2" })],
          "IN",
        )}
        isCorrection
      />,
    );

    expect(screen.getByText("Correction: +0 / −2")).toBeInTheDocument();
    expect(snapshotValue("Added")).toBe("0");
    expect(snapshotValue("Removed")).toBe("2");
  });
});
