import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test/utils";
import WmsLotExpiryDialog from "./WmsLotExpiryDialog";

// The camera is a live device; what the dialog does with a read is tested.
vi.mock("@/components/ui/ScanToFill", () => ({
  ScanToFill: ({
    label,
    onCode,
  }: {
    label: string;
    onCode: (code: string) => void;
  }) => (
    <button type="button" onClick={() => onCode("LOT-2026-17")}>
      {label}
    </button>
  ),
}));

function renderDialog(onConfirm = vi.fn()) {
  renderWithProviders(
    <WmsLotExpiryDialog
      productName="Yoghurt"
      isLoading={false}
      onConfirm={onConfirm}
      onCancel={vi.fn()}
    />,
  );
  return onConfirm;
}

describe("WmsLotExpiryDialog", () => {
  it("opens without putting the keyboard over the expiry date", () => {
    renderDialog();

    expect(screen.getByLabelText("Lot")).not.toHaveFocus();
    expect(document.activeElement?.tagName).not.toBe("INPUT");
  });

  it("takes the lot from the camera instead of the keyboard", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.click(
      await screen.findByRole("button", { name: "Scan lot code" }),
    );

    expect(screen.getByLabelText("Lot")).toHaveValue("LOT-2026-17");
  });
});
