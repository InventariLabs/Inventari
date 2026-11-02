import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";

import { ReturnFormModal } from "./ReturnFormModal";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { useFormGuardStore } from "@/store/formGuardStore";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

const { mutateMock } = vi.hoisted(() => ({ mutateMock: vi.fn() }));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useCreateReturn: () => ({
    mutate: mutateMock,
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

function buildDocument(type: string): WarehouseDocument {
  return {
    id: "doc-1",
    type,
    number: `${type}/2026/058`,
    status: "COMPLETED",
    lines: [
      {
        id: "line-1",
        line_number: 1,
        name: "Widget",
        quantity: 3,
        done_quantity: 3,
      },
    ],
  } as unknown as WarehouseDocument;
}

describe("ReturnFormModal", () => {
  it("names the document type the return will actually create", () => {
    // The warning was a fixed sentence promising a receipt (IN). A return of
    // an internal transfer creates another INT, so the sentence was only ever
    // true for dispatches.
    render(
      <ReturnFormModal document={buildDocument("INT")} onClose={vi.fn()} />,
    );

    expect(
      screen.getByText(/A new Transfer document will be created/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/receipt document \(IN\)/),
    ).not.toBeInTheDocument();
  });

  it("still names a receipt when returning a dispatch", () => {
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    expect(
      screen.getByText(/A new Receipt document will be created/),
    ).toBeInTheDocument();
  });

  it("will not send a return without a reason from the list", async () => {
    const user = userEvent.setup();
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "1" },
    });
    await user.click(screen.getByRole("button", { name: /create return/i }));

    expect(mutateMock).not.toHaveBeenCalled();
    expect(screen.getByText("Pick a reason")).toBeInTheDocument();
  });

  it("sends the reason code with the return", async () => {
    const user = userEvent.setup();
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "1" },
    });
    await user.selectOptions(
      screen.getByTestId("return-reason-code"),
      "DAMAGED",
    );
    await user.click(screen.getByRole("button", { name: /create return/i }));

    expect(mutateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({ reason_code: "DAMAGED" }),
      }),
      expect.any(Object),
    );
  });

  it("asks what happened when the reason is 'Other'", async () => {
    const user = userEvent.setup();
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "1" },
    });
    await user.selectOptions(screen.getByTestId("return-reason-code"), "OTHER");
    await user.click(screen.getByRole("button", { name: /create return/i }));

    expect(mutateMock).not.toHaveBeenCalled();
    expect(
      screen.getByText("Say what happened, or pick a named reason"),
    ).toBeInTheDocument();
  });

  describe("leaving a filled-in sheet", () => {
    it("asks before Escape throws away an entered quantity", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.keyboard("{Escape}");

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the close button discards it", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.click(screen.getByRole("button", { name: "Close" }));

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before a click on the backdrop discards it", async () => {
      const onClose = vi.fn();
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
      fireEvent.mouseDown(backdrop);
      fireEvent.click(backdrop);

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the cancel button discards it, and closes on confirm", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(onClose).not.toHaveBeenCalled();

      await user.click(await screen.findByRole("button", { name: "Discard" }));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it("tells the navigation gate, so a header link asks too", () => {
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
      );
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();

      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      expect(useFormGuardStore.getState().dirtyForm).toBe("The return form");
    });

    it("closes an untouched sheet without a question", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <ReturnFormModal document={buildDocument("OUT")} onClose={onClose} />,
      );

      await user.keyboard("{Escape}");

      expect(onClose).toHaveBeenCalledOnce();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });
});
