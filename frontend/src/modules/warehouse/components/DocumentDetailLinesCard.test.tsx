import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, it, expect } from "vitest";
import { render } from "@/test/utils";
import { DocumentDetailLinesCard } from "./DocumentDetailLinesCard";
import { userEvent } from "@testing-library/user-event";
import { vi } from "vitest";
import type {
  DocumentLine,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import * as modulesCtx from "@/contexts/ModulesContext";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { api } from "@/lib/api/client";
import { serveLocations } from "@/test/serveLocations";

// The price columns follow the profile as well as the document type, so the
// profile is the test's to state.
let valueTracking = true;
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: valueTracking },
  }),
}));

function line(overrides: Partial<DocumentLine>): DocumentLine {
  return documentLine({
    id: "l1",
    document_id: "d1",
    item_id: null,
    product_template_id: null,
    name: "Bolts M8",
    brand: null,
    barcode: null,
    quantity: "10",
    expected_quantity: "10",
    done_quantity: "0",
    uom: null,
    batch_number: null,
    expiry_date: null,
    notes: null,
    line_number: 1,
    ...overrides,
  });
}

function doc(
  lines: DocumentLine[],
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "d1",
    organization_id: "o1",
    type: "IN",
    number: "IN/2026/008",
    status: "CONFIRMED",
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines,
    created_by: "u1",
    confirmed_by: null,
    created_at: "2026-08-01T10:00:00Z",
    updated_at: "2026-08-01T10:00:00Z",
    confirmed_at: null,
    completed_at: null,
    ...overrides,
  });
}

function renderCard(
  lines: DocumentLine[],
  overrides: Partial<WarehouseDocument> = {},
  cardOverrides: Partial<Parameters<typeof DocumentDetailLinesCard>[0]> = {},
) {
  return render(
    <DocumentDetailLinesCard
      document={doc(lines, overrides)}
      formatQuantity={(v) => String(v)}
      {...cardOverrides}
    />,
  );
}

describe("DocumentDetailLinesCard — a correction's line", () => {
  it("reads in stock terms, like the summary above it", () => {
    // Less issued puts goods back: the line said "-1" under "+1 / −0".
    renderCard([line({ quantity: "-1", expected_quantity: "-1" })], {
      type: "CORRECTION",
      corrects_document_type: "OUT",
    });
    expect(screen.getAllByText("+1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("added to stock").length).toBeGreaterThan(0);
  });

  it("takes goods off stock when a receipt is corrected downwards", () => {
    renderCard([line({ quantity: "-2", expected_quantity: "-2" })], {
      type: "CORRECTION",
      corrects_document_type: "IN",
    });
    expect(screen.getAllByText("-2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("removed from stock").length).toBeGreaterThan(0);
  });
});

describe("DocumentDetailLinesCard — quantity column", () => {
  it("shows no bar under the quantity when nothing is executed", () => {
    // A grey track under every number in a read-only table reads as an
    // underlined input: the view looked like a form.
    renderCard([line({ done_quantity: "0" })]);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("shows no bar when the line is fully executed", () => {
    // A full bar repeats what the status says.
    renderCard([line({ done_quantity: "10" })]);
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("shows a labelled meter while the line is part-done", () => {
    renderCard([line({ done_quantity: "4" })]);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "4");
    expect(meter).toHaveAttribute("aria-valuemax", "10");
  });

  it("prints the received number next to the planned one while part-done", () => {
    // The done number used to live only in a title attribute - invisible on
    // touch, in print, and in copied text - while the Quantity column read
    // the planned figure alone.
    renderCard([line({ done_quantity: "4" })]);
    // The mobile card variant already prints it; the desktop table used to
    // hide the number in a title attribute - invisible on touch, in print
    // and in copied text. Both variants have to print it.
    expect(
      screen.getAllByText(/done 4 \/ planned 10/i).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("prints done 0 for an untouched line while its neighbours have moved", () => {
    // On a part-done receipt an untouched line printed the planned number
    // alone - the same contradiction as the tooltip: the column said 3,
    // nothing said nothing arrived. Next to neighbours counting their
    // deliveries, the planned number reads as arrived.
    renderCard([
      line({
        id: "l1",
        line_number: 1,
        expected_quantity: "4",
        done_quantity: "3",
      }),
      line({
        id: "l2",
        line_number: 2,
        name: "Nuts M6",
        expected_quantity: "3",
        done_quantity: "0",
      }),
    ]);
    // Twice: the table and the card variant both print it.
    expect(
      screen.getAllByText(/done 0 \/ planned 3/i).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("prints done 0 on a completed receipt where nothing arrived", () => {
    // A completed document's zeros are a result, not the absence of one:
    // the run happened, and "3" alone read as three pieces received.
    renderCard(
      [
        line({
          id: "l1",
          line_number: 1,
          name: "Nuts M6",
          expected_quantity: "3",
          done_quantity: "0",
        }),
        line({
          id: "l2",
          line_number: 2,
          name: "Washers M8",
          expected_quantity: "2",
          done_quantity: "0",
        }),
      ],
      { status: "COMPLETED" },
    );
    expect(
      screen.getAllByText(/done 0 \/ planned 3/i).length,
    ).toBeGreaterThanOrEqual(2);
    expect(
      screen.getAllByText(/done 0 \/ planned 2/i).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("prints the received number as the line's quantity when it exceeds the plan", () => {
    // A receipt without an order raised from 1 to 5 on the phone sheet: the
    // line printed the plan (1) and only the summary knew 5 entered stock.
    const { container } = renderCard(
      [line({ quantity: "1", expected_quantity: "1", done_quantity: "5" })],
      { status: "COMPLETED" },
    );
    const cell = container.querySelector("table tbody td.font-mono");
    expect(cell?.querySelector(".font-semibold")).toHaveTextContent(/^5$/);
    const card = container.querySelector("ul li .font-semibold");
    expect(card).toHaveTextContent(/^5$/);
    expect(screen.getAllByText(/done 5 \/ planned 1/i).length).toBe(2);
  });

  it("compares wire quantities numerically, not lexicographically", () => {
    // The API ships quantities as decimal strings, and "3.000" < "10.000"
    // is false read as text — a line done 3 of 10 then printed its plan
    // alone, silently disagreeing with the list's 3/10.
    // The hand-written type says `number`, but the wire ships decimal
    // strings — the fixture carries the wire's shape, cast to fit the type
    // until the module's quantity types tell the truth.
    renderCard(
      [
        line({
          id: "l1",
          line_number: 1,
          name: "Nuts M6",
          expected_quantity: "10.000",
          done_quantity: "3.000",
        } as unknown as Partial<DocumentLine>),
      ],
      { status: "COMPLETED" },
    );
    // The sentence carries the wire's raw scale ("3.000"); the point is
    // that it appears at all and in both variants.
    expect(
      screen.getAllByText(/done 3(\.000)? \/ planned 10(\.000)?/i).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("gates the progress bar on wire quantities numerically, for every line", () => {
    // The bar's visibility gate was the one comparison this file's earlier
    // wire test did not cover: read as text, "3.000" < "10.000" is false
    // (the "3" outranks the "1"), so a line done 3 of 10 got no bar while
    // a line done 3 of 4 did — on the same document. Both bars now show.
    renderCard(
      [
        line({
          id: "l1",
          line_number: 1,
          name: "Nuts M6",
          quantity: "10.000",
          expected_quantity: "10.000",
          done_quantity: "3.000",
        } as unknown as Partial<DocumentLine>),
        line({
          id: "l2",
          line_number: 2,
          name: "Washers M8",
          quantity: "4.000",
          expected_quantity: "4.000",
          done_quantity: "3.000",
        } as unknown as Partial<DocumentLine>),
      ],
      { status: "CONFIRMED" },
    );
    // The desktop table draws one bar per part-done line; both of these
    // lines are part-done, so both get one.
    expect(screen.getAllByRole("meter")).toHaveLength(2);
    expect(screen.getAllByRole("meter")[0]).toHaveAttribute(
      "aria-valuemax",
      "10",
    );
  });

  it("stays quiet while nothing on the document has moved", () => {
    // With no delivery at all, a column of "done 0" under every number is
    // noise the status badge already covers.
    renderCard([
      line({ expected_quantity: "4", done_quantity: "0" }),
      line({
        id: "l2",
        line_number: 2,
        name: "Nuts M6",
        expected_quantity: "3",
        done_quantity: "0",
      }),
    ]);
    expect(screen.queryByText(/done 0/i)).not.toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — heading level", () => {
  it("puts the section title one level under the page title", () => {
    renderCard([line({})]);
    expect(screen.getByRole("heading", { level: 2 })).toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — where the goods went", () => {
  it("names the shelf when a putaway rule sent the line elsewhere", () => {
    // The header says Floor 2, the rule sent the delivery to Floor 1, and
    // the document used to say nothing at all about the difference.
    renderCard(
      [
        line({
          executed_location_id: "l-floor1",
          executed_location_name: "Floor 1 - Row A",
        }),
      ],
      { target_location_id: "l-floor2" },
    );
    // Twice: the table for a desktop and the cards for a phone are both in
    // the document, and CSS picks between them.
    expect(screen.getAllByText(/Put away at Floor 1 - Row A/)).toHaveLength(2);
  });

  it("stays quiet when the goods landed where the document asked", () => {
    renderCard(
      [
        line({
          executed_location_id: "l-floor2",
          executed_location_name: "Floor 2 - Row A",
        }),
      ],
      { target_location_id: "l-floor2" },
    );
    expect(screen.queryByText(/Floor 2 - Row A/)).not.toBeInTheDocument();
  });

  it("stays quiet on a document nobody executed yet", () => {
    renderCard([line({})], { target_location_id: "l-floor2" });
    expect(screen.queryByText(/Put away at/)).not.toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — planned putaway", () => {
  it("says where a matching rule will put the line, and by what match", () => {
    // The rule used to decide while booking: the first honest sentence about
    // its choice appeared only after the goods were on the shelf, as "landed
    // elsewhere". Before execution the line now names the shelf up front.
    renderCard([
      line({
        planned_location_id: "loc-1",
        planned_location_name: "Paint Shelf",
        planned_source: "rule",
        planned_rule_id: "r1",
        planned_rule_match_key: "category",
        planned_rule_match_name: "Paints",
      }),
    ]);
    // Both responsive variants render (jsdom keeps the hidden one alive),
    // so the sentence has to be found per variant.
    expect(
      screen.getAllByText(/→ Paint Shelf · rule: category Paints/i).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("says a line of a two-step warehouse lands in its receiving area", () => {
    renderCard([
      line({
        planned_location_id: "area-1",
        planned_location_name: "Receiving",
        planned_source: "receiving",
      }),
    ]);
    expect(
      screen.getAllByText(/→ Receiving · receiving area, put away later/)
        .length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("names an over-full shelf with its numbers", () => {
    // All the rule's shelves are full: the plan still names the first one,
    // but in amber with the arithmetic — the reader can hand the line to
    // another shelf instead of discovering the overflow after booking.
    renderCard([
      line({
        planned_location_id: "loc-1",
        planned_location_name: "Paint Shelf",
        planned_source: "rule",
        planned_rule_id: "r1",
        planned_over_capacity: true,
        planned_capacity_used: "190",
        planned_capacity_max: "200",
      }),
    ]);
    expect(
      screen.getAllByText(/Paint Shelf is full \(190\/200\)/).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("names a shelf other products share by its whole fill", () => {
    // Rice's own 20/40 looks roomy on a shelf plums already fill: the
    // sentence gives the sum of every product's share instead.
    renderCard([
      line({
        planned_location_id: "loc-1",
        planned_location_name: "Mixed Shelf",
        planned_source: "rule",
        planned_rule_id: "r1",
        planned_over_capacity: true,
        planned_capacity_used: "20",
        planned_capacity_max: "40",
        planned_shelf_fill: 110,
      }),
    ]);
    expect(
      screen.getAllByText(
        /Mixed Shelf is 110% full with every product on it counted/,
      ).length,
    ).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/20\/40/)).not.toBeInTheDocument();
  });

  it("says when a matched rule had to step aside for an archived target", () => {
    // The rule matched, but its shelf is gone from the lists: the line fell
    // back to the document's target, and the amber sentence says why —
    // otherwise the fallback would read as if no rule had ever fired.
    renderCard([
      line({
        planned_location_id: "loc-2",
        planned_location_name: "Receiving Dock",
        planned_source: "document",
        planned_rule_id: "r1",
        planned_rule_match_key: "category",
        planned_rule_match_name: "Paints",
        planned_rule_warning: "archived",
      }),
    ]);
    expect(
      screen.getAllByText(/A matching rule points at an archived location/)
        .length,
    ).toBeGreaterThanOrEqual(2);
    // And it says where the goods go instead. The sentence used to stop at
    // the reason, leaving the reader knowing why the rule lost and not the
    // one thing they opened the line to find out.
    expect(
      screen.getAllByText(/the line goes to Receiving Dock/).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("says when a module ruled out every location of the matched rule", () => {
    // A module's putaway criterion turned the rule's locations down for
    // these goods: the same fallback as an archived target, for a reason
    // the locations' own state does not show.
    renderCard([
      line({
        planned_location_id: "loc-2",
        planned_location_name: "Receiving Dock",
        planned_source: "document",
        planned_rule_id: "r1",
        planned_rule_match_key: "category",
        planned_rule_match_name: "Chilled",
        planned_rule_warning: "refused",
      }),
    ]);
    expect(
      screen.getAllByText(
        /A module ruled out every location of a matching rule \(Chilled\).*the line goes to Receiving Dock/,
      ).length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("stays silent while the plan is the document's own target", () => {
    // The header already says where the document is going; a per-line repeat
    // of the same shelf is noise, not information.
    renderCard([
      line({
        planned_location_id: "loc-2",
        planned_location_name: "Receiving Dock",
        planned_source: "document",
      }),
    ]);
    expect(screen.queryByText(/→ Receiving Dock/i)).not.toBeInTheDocument();
  });

  it("stops speaking once the line has executed", () => {
    // After booking, the executed shelf and landedElsewhere own the story; a
    // plan computed past that point would be a second, older answer.
    renderCard([
      line({
        executed_location_id: "loc-1",
        planned_location_id: "loc-1",
        planned_location_name: "Paint Shelf",
        planned_source: "rule",
        planned_rule_id: "r1",
        planned_rule_match_key: "category",
        planned_rule_match_name: "Paints",
      }),
    ]);
    expect(screen.queryByText(/→ Paint Shelf/i)).not.toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — line target picker", () => {
  beforeEach(() => {
    serveLocations([
      { id: "wh", name: "Warehouse" },
      { id: "loc-a", name: "A-12", parent_id: "wh" },
      { id: "loc-b", name: "A-13", parent_id: "wh" },
    ]);
  });

  it("offers the line its own shelf, empty meaning the plan", async () => {
    const onLineTargetChange = vi.fn();
    renderCard(
      [line({ planned_location_id: "loc-a", planned_source: "rule" })],
      { type: "IN", status: "CONFIRMED" },
      { onLineTargetChange },
    );
    const pickers = screen.getAllByRole("combobox", {
      name: /line location/i,
    });
    // Both responsive variants carry the picker.
    expect(pickers.length).toBeGreaterThanOrEqual(2);
    expect(pickers[0]).toHaveTextContent("Follow the plan");

    await userEvent.click(pickers[0]);
    await userEvent.click(await screen.findByRole("button", { name: /A-13/ }));
    expect(onLineTargetChange).toHaveBeenCalledWith("l1", "loc-b");
  });

  it("shows the chosen shelf and can give the say back to the plan", async () => {
    const onLineTargetChange = vi.fn();
    renderCard(
      [line({ target_location_id: "loc-b" })],
      { type: "IN", status: "CONFIRMED" },
      { onLineTargetChange },
    );
    const pickers = screen.getAllByRole("combobox", {
      name: /line location/i,
    });
    await waitFor(() => expect(pickers[0]).toHaveTextContent("A-13"));

    await userEvent.click(pickers[0]);
    await userEvent.click(
      await screen.findByRole("button", { name: /Follow the plan/ }),
    );
    expect(onLineTargetChange).toHaveBeenCalledWith("l1", null);
  });

  it("stays out of a completed document", () => {
    renderCard(
      [line({})],
      { type: "IN", status: "COMPLETED" },
      { onLineTargetChange: vi.fn() },
    );
    expect(
      screen.queryByRole("combobox", { name: /line location/i }),
    ).not.toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — the shelf a zone's line takes from", () => {
  it("names the shelf below the zone each line leaves from", () => {
    // A dispatch from a zone splits its lines over the shelves below; each
    // line has to say which one, or the picker reads only the zone.
    renderCard(
      [
        line({
          source_location_id: "bin-b2",
          source_location_name: "Bin B2",
        }),
      ],
      { type: "OUT", source_location_id: "zone" },
    );
    expect(
      screen.getAllByText("Taken from Bin B2").length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("does not call the shelf goods left from a shelf they were put away at", () => {
    // Completion records the pinned shelf as where the line's goods went,
    // so a correction lands there; for a dispatch that is where they left.
    renderCard(
      [
        line({
          source_location_id: "bin-b2",
          source_location_name: "Bin B2",
          executed_location_id: "bin-b2",
          executed_location_name: "Bin B2",
          done_quantity: "10",
        }),
      ],
      { type: "OUT", status: "COMPLETED", source_location_id: "zone" },
    );
    expect(screen.queryByText(/Put away at/)).not.toBeInTheDocument();
    expect(
      screen.getAllByText("Taken from Bin B2").length,
    ).toBeGreaterThanOrEqual(2);
  });
});

describe("DocumentDetailLinesCard — price and VAT columns", () => {
  beforeEach(() => {
    valueTracking = true;
  });

  it("shows the columns on a receipt whose lines carry a price", () => {
    renderCard([line({ unit_price: "10.00", line_gross: "12.30" })]);

    expect(screen.getByText("Unit price")).toBeInTheDocument();
    expect(screen.getByText("Gross value")).toBeInTheDocument();
  });

  it("shows nothing of price or VAT on a transfer, whatever it holds", () => {
    // A move between shelves asks for no price, so nothing here quotes one
    // — the stored figures stay in the register, untouched.
    renderCard([line({ unit_price: "10.00", line_gross: "12.30" })], {
      type: "INT",
      number: "INT/2026/004",
      source_location_id: "loc-1",
      target_location_id: "loc-2",
    });

    expect(screen.queryByText("Unit price")).not.toBeInTheDocument();
    expect(screen.queryByText("Gross value")).not.toBeInTheDocument();
    expect(screen.queryByText(/10\.00/)).not.toBeInTheDocument();
  });

  it("shows nothing of price or VAT while value is not tracked", () => {
    valueTracking = false;

    renderCard([line({ unit_price: "10.00", line_gross: "12.30" })]);

    expect(screen.queryByText("Unit price")).not.toBeInTheDocument();
    expect(screen.queryByText(/10\.00/)).not.toBeInTheDocument();
  });
});

describe("DocumentDetailLinesCard — what another module says about a line", () => {
  it("offers every line to the module, in the table and in the phone's cards", () => {
    function Certificate({
      data,
    }: {
      data: SlotDataMap["document_detail_line_extra"];
    }) {
      return (
        <p>
          Certificate for {data.line.name} #{data.line.lineNumber} of{" "}
          {data.documentId} ({data.documentStatus}):{" "}
          {String(data.line.metaData.slot_probe?.number ?? "none")}
        </p>
      );
    }
    moduleRegistry.register({
      name: "slot-probe",
      routes: [],
      slots: [
        {
          slot: "document_detail_line_extra",
          component: slotComponent(Certificate),
        },
      ],
    });
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse", "slot-probe"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    } as unknown as ReturnType<typeof modulesCtx.useModules>);

    renderCard([
      line({
        id: "l1",
        name: "Bolts M8",
        line_number: 1,
        meta_data: { slot_probe: { number: "C-1" } },
      }),
      line({ id: "l2", name: "Nuts M8", line_number: 2 }),
    ]);

    // Once in the table and once in the card, for each of the two lines.
    expect(
      screen.getAllByText("Certificate for Bolts M8 #1 of d1 (CONFIRMED): C-1"),
    ).toHaveLength(2);
    expect(
      screen.getAllByText("Certificate for Nuts M8 #2 of d1 (CONFIRMED): none"),
    ).toHaveLength(2);
  });
  it("lets the module fill its field on a line of the saved document", async () => {
    const put = vi.spyOn(api, "put").mockResolvedValue({ data: {} });
    function CertificateButton({
      data,
    }: {
      data: SlotDataMap["document_detail_line_extra"];
    }) {
      return (
        <button
          type="button"
          onClick={() =>
            void data.saveMetaData("slot_probe", { number: "C-9" })
          }
        >
          Save certificate for {data.line.name}
        </button>
      );
    }
    moduleRegistry.register({
      name: "slot-probe",
      routes: [],
      slots: [
        {
          slot: "document_detail_line_extra",
          component: slotComponent(CertificateButton),
        },
      ],
    });
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse", "slot-probe"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    } as unknown as ReturnType<typeof modulesCtx.useModules>);
    renderCard([line({ id: "l1", name: "Bolts M8", line_number: 1 })]);

    await userEvent.click(
      screen.getAllByRole("button", {
        name: "Save certificate for Bolts M8",
      })[0],
    );

    expect(put).toHaveBeenCalledWith(
      "/warehouse/documents/d1/lines/l1/meta-data/slot_probe",
      { number: "C-9" },
    );
    put.mockRestore();
  });
});
