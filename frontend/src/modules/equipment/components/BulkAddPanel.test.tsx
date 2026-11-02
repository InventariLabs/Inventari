import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import BulkAddPanel from "./BulkAddPanel";

function renderPanel(onSubmit = vi.fn()) {
  render(<BulkAddPanel onSubmit={onSubmit} onCancel={vi.fn()} />);
  return onSubmit;
}

describe("BulkAddPanel", () => {
  // Same contract as every quantity field in the tree: the cleared keystroke
  // must survive until the next digit — a field that restores its old number
  // turns "clear, then type 3" into "append to what stood there".
  it("lets the quantity be cleared before the new number is typed", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Generate" }));
    const field = screen.getByLabelText("Quantity");

    await user.clear(field);
    expect(field).toHaveValue(null);

    await user.type(field, "3");
    await user.click(screen.getByRole("button", { name: /Generate/ }));

    expect(screen.getAllByLabelText("Serial number")).toHaveLength(3);
  });

  // Expected green on the pre-fix behaviour as well: the clamp answered an
  // empty field with the floor of 1. It pins that the freed-up empty state
  // generates a real row instead of zero or NaN rows.
  it("generates one row when the generate lands on a cleared field", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole("tab", { name: "Generate" }));
    const field = screen.getByLabelText("Quantity");

    await user.clear(field);
    await user.click(screen.getByRole("button", { name: /Generate/ }));

    expect(screen.getAllByLabelText("Serial number")).toHaveLength(1);
  });
});

/**
 * What the panel hands to the create call is the whole point of it: one row
 * per serial, the asset tag only where the reader asked for it, and nothing
 * at all while two rows share a serial — the server would create one and
 * refuse the other, leaving a half-made batch.
 */
describe("BulkAddPanel — what reaches the create call", () => {
  it("turns a pasted list into one trimmed row per non-empty line", async () => {
    const user = userEvent.setup();
    const onSubmit = renderPanel();

    await user.type(
      screen.getByLabelText("Serial numbers"),
      "  SN-1 {Enter}{Enter}SN-2{Enter}",
    );
    expect(screen.getByRole("status")).toHaveTextContent("2 serials detected");

    await user.click(screen.getByRole("button", { name: "Create 2 assets" }));
    expect(onSubmit).toHaveBeenCalledWith(
      [
        { serial_number: "SN-1", asset_tag: undefined },
        { serial_number: "SN-2", asset_tag: undefined },
      ],
      { assignLabels: false, qrOnly: false },
    );
  });

  it("refuses to create while two rows share a serial, and lets an edit clear it", async () => {
    const user = userEvent.setup();
    const onSubmit = renderPanel();

    await user.type(screen.getByLabelText("Serial numbers"), "SN-1{Enter}SN-1");
    expect(
      screen.getByText("Duplicate serial numbers detected."),
    ).toHaveAttribute("role", "alert");
    // Each clashing row says so beside itself, too.
    expect(screen.getAllByText("Duplicate")).toHaveLength(2);
    const create = screen.getByRole("button", { name: "Create 2 assets" });
    expect(create).toBeDisabled();

    const rows = screen.getAllByLabelText("Serial number");
    await user.type(rows[1], "b");
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    await user.click(create);
    expect(onSubmit.mock.calls[0][0]).toEqual([
      { serial_number: "SN-1", asset_tag: undefined },
      { serial_number: "SN-1b", asset_tag: undefined },
    ]);
  });

  it("drops a removed row from what is sent", async () => {
    const user = userEvent.setup();
    const onSubmit = renderPanel();

    await user.type(screen.getByLabelText("Serial numbers"), "A{Enter}B");
    await user.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await user.click(screen.getByRole("button", { name: "Create 1 asset" }));
    expect(onSubmit.mock.calls[0][0]).toEqual([
      { serial_number: "B", asset_tag: undefined },
    ]);
  });

  it("copies each serial into the asset tag when asked, and follows later edits", async () => {
    const user = userEvent.setup();
    const onSubmit = renderPanel();

    await user.type(screen.getByLabelText("Serial numbers"), "A{Enter}B");
    await user.click(screen.getByLabelText("Use serial number as asset tag"));
    await user.type(screen.getAllByLabelText("Serial number")[1], "2");
    await user.click(screen.getByRole("button", { name: "Create 2 assets" }));
    expect(onSubmit.mock.calls[0][0]).toEqual([
      { serial_number: "A", asset_tag: "A" },
      { serial_number: "B2", asset_tag: "B2" },
    ]);
  });

  it("generates numbered serials from the asset's name and carries the label choice", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <BulkAddPanel
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        assetName="Dell Latitude 5540"
      />,
    );

    await user.click(screen.getByRole("tab", { name: "Generate" }));
    const quantity = screen.getByLabelText("Quantity");
    await user.clear(quantity);
    await user.type(quantity, "10");
    await user.click(
      screen.getByRole("button", { name: "Generate 10 serial numbers" }),
    );
    await user.click(screen.getByLabelText("Generate & assign QR labels"));
    await user.click(screen.getByLabelText("QR square only"));
    await user.click(screen.getByRole("button", { name: "Create 10 assets" }));

    const [entries, options] = onSubmit.mock.calls[0];
    expect(entries[0].serial_number).toBe("DELL-LATITUD-01");
    expect(entries[9].serial_number).toBe("DELL-LATITUD-10");
    expect(options).toEqual({ assignLabels: true, qrOnly: true });

    await user.click(screen.getByLabelText("Name"));
    await user.click(screen.getByRole("button", { name: "Create 10 assets" }));
    expect(onSubmit.mock.calls[1][1]).toEqual({
      assignLabels: true,
      qrOnly: false,
    });
  });

  it("falls back to a generic prefix when the prefix is cleared", async () => {
    const user = userEvent.setup();
    const onSubmit = renderPanel();

    await user.click(screen.getByRole("tab", { name: "Generate" }));
    await user.clear(screen.getByLabelText("Prefix"));
    await user.click(
      screen.getByRole("button", { name: "Generate 1 serial number" }),
    );
    await user.click(screen.getByRole("button", { name: "Create 1 asset" }));
    expect(onSubmit.mock.calls[0][0][0].serial_number).toBe("ASSET-1");
  });

  it("hands Cancel back to the page", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<BulkAddPanel onSubmit={vi.fn()} onCancel={onCancel} />);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
