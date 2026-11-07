import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import { ReceiveLineRow } from "./ReceiveLineRow";
import type { ReceiveDraftLine } from "./receiveDraft";
import type { PutawayPreviewLine } from "@/modules/warehouse/api/putaway";

const line: ReceiveDraftLine = {
  key: "row-1",
  itemId: null,
  productTemplateId: "tpl-1",
  name: "ThinkPad T14s",
  sku: "TP-14",
  barcode: null,
  uomId: null,
  uomSymbol: "pcs",
  ordered: "2",
  quantity: "2",
  targetLocationId: null,
  batchNumber: "",
  expiryDate: "",
  unitPrice: "12345.67",
  taxRate: "23.00",
  sourcePoLineId: null,
  chosenProductName: null,
  heldQuantity: "",
  heldCode: "DAMAGE",
};

const plan = {
  planned_location_id: "loc-a",
  planned_location_name: "A-13",
  planned_source: "line",
  planned_rule_match_key: null,
  planned_rule_match_name: null,
  planned_rule_warning: null,
  planned_over_capacity: false,
  planned_capacity_used: null,
  planned_capacity_max: null,
  planned_shelf_fill: null,
} as PutawayPreviewLine;

function renderRow(props: {
  plan?: PutawayPreviewLine;
  planChecking?: boolean;
  line?: ReceiveDraftLine;
  onUpdate?: () => void;
  needsExpiry?: boolean;
}) {
  return render(
    <table>
      <tbody>
        <ReceiveLineRow
          line={props.line ?? line}
          registerBeforeSubmit={vi.fn()}
          index={0}
          plan={props.plan}
          planChecking={props.planChecking ?? false}
          showPrices
          showTax
          canWrite
          focusLineKey={null}
          shortLine={false}
          needsExpiry={props.needsExpiry ?? false}
          onFocusHandled={vi.fn()}
          onUpdate={props.onUpdate ?? vi.fn()}
          onRemove={vi.fn()}
          onQuantityEnter={vi.fn()}
        />
      </tbody>
    </table>,
  );
}

describe("ReceiveLineRow held goods", () => {
  it("keeps the damaged quantity out of sight until it is asked for", () => {
    renderRow({});

    expect(screen.queryByLabelText(/Damaged or on hold:/)).toBeNull();
  });

  it("opens the quantity and the reason, and sends what is typed", async () => {
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    renderRow({ onUpdate });

    await user.click(
      screen.getByRole("button", { name: "Damaged or on hold" }),
    );
    await user.type(screen.getByLabelText(/Damaged or on hold: ThinkPad/), "1");

    expect(onUpdate).toHaveBeenCalledWith("row-1", { heldQuantity: "1" });
    expect(screen.getByRole("combobox", { name: "Why" })).toHaveDisplayValue(
      "Damage",
    );
  });

  it("shows a row that already holds goods back with its fields open", () => {
    renderRow({ line: { ...line, heldQuantity: "2" } });

    expect(screen.getByLabelText(/Damaged or on hold: ThinkPad/)).toHaveValue(
      "2",
    );
  });
});

describe("ReceiveLineRow layout", () => {
  it("puts the plan sentence below the shelf select, not above it", () => {
    renderRow({ plan });

    const select = screen.getByRole("combobox");
    const sentence = screen.getByText(/A-13/);
    // Above the select the sentence made the cell two lines tall and
    // pushed the select off the line the other inputs sit on.
    expect(
      select.compareDocumentPosition(sentence) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("leaves the select alone when there is no plan to report", () => {
    renderRow({ plan: undefined, planChecking: false });

    expect(screen.queryByText(/No location yet/i)).not.toBeInTheDocument();
    const cell = screen.getByRole("combobox").closest("td");
    expect(cell?.querySelector("span.text-xs")).toBeNull();
  });

  it("reads 'follow the plan' on the shelf field until a shelf is named", () => {
    renderRow({ plan });

    expect(
      screen.getByRole("combobox", { name: "Line location" }),
    ).toHaveTextContent("Follow the plan (rule / document)");
  });

  it("keeps the lot and expiry control at the left edge of the product cell", () => {
    renderRow({ plan });

    // In a stretching flex column the button took the full width and
    // centred its text in the middle of the cell.
    expect(screen.getByRole("button", { name: "Lot and expiry" })).toHaveClass(
      "self-start",
    );
  });

  it("gives the VAT rate room for a full five-character value", () => {
    renderRow({ plan });

    const vat = screen.getByLabelText(/VAT/i);
    expect(vat).toHaveValue("23.00");
    expect(vat.closest("div.w-20")).not.toBeNull();
  });
});

describe("ReceiveLineRow expiry refused by the server", () => {
  it("opens the lot and expiry fields and says the date is needed", () => {
    renderRow({ needsExpiry: true });

    expect(screen.getByLabelText("Expiry")).toBeVisible();
    expect(screen.getByText("Needed for this product")).toBeInTheDocument();
  });

  it("stops asking once the row carries a date", () => {
    renderRow({
      needsExpiry: true,
      line: { ...line, expiryDate: "2027-01-31" },
    });

    expect(
      screen.queryByText("Needed for this product"),
    ).not.toBeInTheDocument();
  });

  it("keeps the fields folded for a row nobody refused", () => {
    renderRow({});

    expect(screen.queryByLabelText("Expiry")).not.toBeInTheDocument();
  });
});
