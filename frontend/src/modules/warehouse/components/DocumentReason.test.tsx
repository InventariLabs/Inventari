import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DocumentCorrectionsSection } from "./DocumentCorrectionsSection";
import { DocumentMetadataGrid } from "./DocumentMetadataGrid";
import type { DocumentSummary, WarehouseDocument } from "../types";

/**
 * The correction form refuses to save without a reason, then no screen
 * ever showed the answer. These two renders are where the reason belongs:
 * the correction's own card, and the parent's list of corrections.
 */

const t = (key: string, opts?: Record<string, unknown>) => {
  const table: Record<string, string> = {
    "warehouse:fields.confirmedAt": "Confirmed",
    "warehouse:fields.confirmedBy": "Confirmed by",
    "warehouse:reasons.correction.label": "Reason for correcting",
    "warehouse:reasons.return.label": "Reason for the return",
    "warehouse:reasons.correction.codes.WRONG_QUANTITY": "Wrong quantity",
    "warehouse:reasons.return.codes.DAMAGED": "Damaged",
    "warehouse:returns.isReturnOf": "Return of",
    "warehouse:fields.targetLocation": "To location",
    "warehouse:fields.sourceLocation": "From location",
  };
  let out = table[key] ?? key;
  if (opts)
    for (const [k, v] of Object.entries(opts)) {
      out = out.replace(`{{${k}}}`, String(v));
    }
  return out;
};

function correctionDoc(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return {
    id: "doc-1",
    organization_id: "org-1",
    type: "CORRECTION",
    number: "CORRECTION/2026/006",
    status: "COMPLETED",
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [],
    created_by: "u-1",
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
    confirmed_at: null,
    completed_at: null,
    reason_code: "WRONG_QUANTITY",
    ...overrides,
  } as unknown as WarehouseDocument;
}

describe("DocumentMetadataGrid", () => {
  it("names the reason a correction was raised, translated", () => {
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc()}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Reason for correcting")).toBeInTheDocument();
    expect(screen.getByText("Wrong quantity")).toBeInTheDocument();
    expect(screen.queryByText("WRONG_QUANTITY")).toBeNull();
  });

  it("reads a return receipt's place, its target, as where the goods go to", () => {
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({
            type: "IN",
            reason_code: null,
            source_location_id: null,
            target_location_id: "loc-1",
          })}
          isDraft
          partners={[]}
          storages={[{ id: "loc-1", name: "Main Warehouse" } as never]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("To location")).toBeVisible();
    expect(screen.queryByText("From location")).toBeNull();
    expect(screen.getByText("Main Warehouse")).toBeVisible();
  });

  it("names a return's reason through the return dictionary", () => {
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({ type: "IN", reason_code: "DAMAGED" })}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Reason for the return")).toBeInTheDocument();
    expect(screen.getByText("Damaged")).toBeInTheDocument();
  });

  it("names the document a return reverses", () => {
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({
            type: "IN",
            reason_code: null,
            return_of_id: "doc-9",
            return_of_number: "OUT/2026/004",
          } as Partial<WarehouseDocument>)}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Return of")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OUT/2026/004" })).toHaveAttribute(
      "href",
      "/warehouse/documents/doc-9",
    );
  });

  it("shows nothing when the document carries no reason", () => {
    // Documents the pre-fix behaviour, not the repair — a document without
    // a reason renders the same with and without the reason cell.
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({ reason_code: null })}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

    expect(screen.queryByText("Reason for correcting")).toBeNull();
  });
});

describe("DocumentCorrectionsSection", () => {
  const corrections: DocumentSummary[] = [
    {
      id: "c-1",
      number: "CORRECTION/2026/006",
      type: "CORRECTION",
      status: "COMPLETED",
      created_at: "2026-09-01T09:00:00Z",
      reason_code: "WRONG_QUANTITY",
    },
  ];

  it("names each correction's reason next to its number", () => {
    render(
      <MemoryRouter>
        <DocumentCorrectionsSection
          corrections={corrections}
          documentType="IN"
          onNewCorrection={() => {}}
          correctionsTitle="Corrections"
          correctionsNewText="New correction"
          correctionsNoneText="No corrections"
          formatReason={(code) =>
            t(`warehouse:reasons.correction.codes.${code}`)
          }
          formatDate={() => "2026-09-01"}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("CORRECTION/2026/006")).toBeInTheDocument();
    expect(screen.getByText("Wrong quantity")).toBeInTheDocument();
    expect(screen.queryByText("WRONG_QUANTITY")).toBeNull();
  });

  it.each([
    ["SCRAP", true],
    ["ADJUSTMENT", false],
  ])("offers a new correction on a completed %s: %s", (type, offered) => {
    // A scrap is corrected like a delivery. An adjustment is refused by the
    // API — its lines are already differences — so the button would only
    // open a form that cannot be saved.
    render(
      <MemoryRouter>
        <DocumentCorrectionsSection
          corrections={[]}
          documentType={type}
          onNewCorrection={() => {}}
          correctionsTitle="Corrections"
          correctionsNewText="New correction"
          correctionsNoneText="No corrections"
          formatReason={(code) => code}
          formatDate={() => "2026-09-01"}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByText("New correction") !== null).toBe(offered);
  });

  it.each([
    ["PENDING_APPROVAL", undefined],
    ["DRAFT", { status: "REJECTED" }],
  ])(
    "shows no confirmation stamp on a %s document left with one by the old code",
    (status, approval) => {
      render(
        <MemoryRouter>
          <DocumentMetadataGrid
            doc={correctionDoc({
              type: "IN",
              status,
              reason_code: null,
              confirmed_at: "2026-10-10T09:00:00Z",
              confirmed_by: "u-1",
              confirmed_by_name: "Rita Requester",
              approval,
            } as Partial<WarehouseDocument>)}
            isDraft={false}
            partners={[]}
            storages={[]}
            notesEditValue={null}
            onNotesChange={() => {}}
            onNotesBlur={() => {}}
            onPartnerChange={() => {}}
            formatDate={(d) => d ?? ""}
            formatDateTime={(d) => d ?? ""}
            t={t}
          />
        </MemoryRouter>,
      );
      expect(screen.queryByText("warehouse:fields.confirmedAt")).toBeNull();
      expect(screen.queryByText("Rita Requester")).toBeNull();
    },
  );

  it("keeps the confirmation a withdrawn request left behind", () => {
    // Withdrawing takes back the question, not the act that asked it: the
    // document stands confirmed and the card names who confirmed it.
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({
            type: "IN",
            status: "CONFIRMED",
            reason_code: null,
            confirmed_at: "2026-10-10T09:00:00Z",
            confirmed_by: "u-1",
            confirmed_by_name: "Rita Requester",
            approval: { status: "CANCELLED" },
          } as Partial<WarehouseDocument>)}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={(d) => d ?? ""}
          formatDateTime={(d) => d ?? ""}
          t={t}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("Rita Requester")).toBeInTheDocument();
    expect(screen.getByText("Confirmed by")).toBeInTheDocument();
  });

  it("names the confirmer, dated at the approval, on a document the approval let through", () => {
    // The approval does not overwrite the confirmation: the hand that
    // confirmed the document keeps its name, dated when it became confirmed.
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={correctionDoc({
            type: "IN",
            status: "CONFIRMED",
            reason_code: null,
            confirmed_at: "2026-10-10T09:00:00Z",
            confirmed_by: "u-1",
            confirmed_by_name: "Rita Requester",
            approval: {
              status: "APPROVED",
              created_at: "2026-10-10T09:00:00Z",
              decisions: [
                { status: "APPROVED", decided_at: "2026-10-10T10:00:00Z" },
              ],
            },
          } as Partial<WarehouseDocument>)}
          isDraft={false}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={(d) => d ?? ""}
          formatDateTime={(d) => d ?? ""}
          t={t}
        />
      </MemoryRouter>,
    );
    expect(screen.getAllByText("2026-10-10T10:00:00Z").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Rita Requester")).toBeInTheDocument();
    expect(screen.getByText("Confirmed by")).toBeInTheDocument();
  });
});

describe("DocumentMetadataGrid partner picker", () => {
  const renderGrid = (doc: WarehouseDocument, isDraft: boolean) =>
    render(
      <MemoryRouter>
        <DocumentMetadataGrid
          doc={doc}
          isDraft={isDraft}
          partners={[]}
          storages={[]}
          notesEditValue={null}
          onNotesChange={() => {}}
          onNotesBlur={() => {}}
          onPartnerChange={() => {}}
          formatDate={() => "2026-09-01"}
          formatDateTime={() => "2026-09-01 09:00"}
          t={t}
        />
      </MemoryRouter>,
    );

  it("gives the picker of a draft the whole row below sm", () => {
    // Half of a phone grid is ~150 px: the placeholder wrapped onto three
    // lines. The picker takes both columns there and one from sm up.
    const { container } = renderGrid(
      correctionDoc({ type: "INT", reason_code: null }),
      true,
    );
    const cell = container.querySelector("button")?.closest("div.col-span-2");
    expect(cell?.className).toContain("sm:col-span-1");
  });

  it("leaves a plain partner name in its single column", () => {
    const { container } = renderGrid(
      correctionDoc({
        type: "IN",
        reason_code: null,
        partner_snapshot: { name: "Acme" },
      } as Partial<WarehouseDocument>),
      false,
    );
    expect(container.querySelector(".col-span-2")).toBeNull();
    expect(screen.getByText("Acme")).toBeInTheDocument();
  });
});
