/**
 * The maintenance type must not open on "Inspection" — the fourth chip of
 * five, and the one that says least about what was actually done — or whoever
 * filed quickly would file that, and the log would fill with inspections.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { render } from "@/test/utils";
import { MaintenanceLogModal } from "@/modules/equipment/components/MaintenanceLogModal";

vi.mock("@/modules/equipment/hooks/useEquipment", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/equipment/hooks/useEquipment")
  >("@/modules/equipment/hooks/useEquipment");
  return {
    ...actual,
    useCreateMaintenanceLog: () => ({ mutate: vi.fn(), isPending: false }),
  };
});

const open = () =>
  render(
    <MaintenanceLogModal
      itemId="item-1"
      itemName="Rack 42U"
      onClose={vi.fn()}
    />,
  );

describe("MaintenanceLogModal", () => {
  it("opens with no type chosen", () => {
    open();

    for (const label of ["Repair", "Cleaning", "Upgrade", "Inspection"]) {
      expect(screen.getByRole("radio", { name: label })).toHaveAttribute(
        "aria-checked",
        "false",
      );
    }
  });

  /**
   * Save with an answer missing says which one: a toast, text at the field and
   * `aria-invalid`.
   */
  it("says which answer is missing instead of greying Save out", async () => {
    const user = userEvent.setup();
    open();

    await user.type(screen.getByRole("textbox", { name: /title/i }), "Fan");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeEnabled();

    await user.click(save);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Choose what kind of work this was",
    );
    expect(screen.getByRole("radiogroup", { name: /Type/ })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("clears the complaint as soon as the answer arrives", async () => {
    const user = userEvent.setup();
    open();

    await user.type(screen.getByRole("textbox", { name: /title/i }), "Fan");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await user.click(screen.getByRole("radio", { name: "Repair" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
