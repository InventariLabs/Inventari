import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@/test/utils";
import i18n from "@/i18n/config";
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
  afterEach(async () => {
    await act(() => i18n.changeLanguage("en"));
  });

  it("writes the quantity limit with the reader's decimal mark", async () => {
    await act(() => i18n.changeLanguage("pl"));
    const document = buildDocument("OUT");
    document.lines[0].done_quantity = "2.5";

    render(<ReturnFormModal document={document} onClose={vi.fn()} />);

    expect(screen.getByText("Maks: 2,5")).toBeInTheDocument();
  });

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

  it("flags a quantity above the maximum and holds the button back", async () => {
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "9" },
    });

    expect(screen.getByRole("spinbutton")).toHaveValue(9);
    expect(screen.getByText("Can't return more than 3")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create return/i }),
    ).toBeDisabled();
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("leaves out a line with nothing left to return", () => {
    const document = buildDocument("OUT");
    document.lines.push({
      id: "line-2",
      line_number: 2,
      name: "Flour",
      quantity: 5,
      done_quantity: 0,
    } as unknown as WarehouseDocument["lines"][number]);
    render(<ReturnFormModal document={document} onClose={vi.fn()} />);

    expect(screen.getByText("Widget")).toBeInTheDocument();
    expect(screen.queryByText("Flour")).not.toBeInTheDocument();
  });

  it("limits a line to what earlier returns left of it", () => {
    const document = buildDocument("OUT");
    document.lines.push(
      ...([
        {
          id: "line-2",
          line_number: 2,
          name: "Bolt",
          quantity: 2,
          done_quantity: 2,
          returnable_quantity: 0,
        },
        {
          id: "line-3",
          line_number: 3,
          name: "Nail",
          quantity: 3,
          done_quantity: 3,
          returnable_quantity: 1,
        },
      ] as unknown as WarehouseDocument["lines"]),
    );
    render(<ReturnFormModal document={document} onClose={vi.fn()} />);

    expect(screen.queryByText("Bolt")).not.toBeInTheDocument();
    expect(screen.getByText("Max: 1")).toBeInTheDocument();
    fireEvent.change(screen.getAllByRole("spinbutton")[1], {
      target: { value: "3" },
    });
    expect(screen.getByText("Can't return more than 1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /create return/i }),
    ).toBeDisabled();
  });

  it("reads a digit typed left of the zero as that digit", () => {
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "90" },
    });

    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe(
      "9",
    );
  });

  it("does not keep the zero in front of a typed digit", () => {
    render(
      <ReturnFormModal document={buildDocument("OUT")} onClose={vi.fn()} />,
    );

    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "02" },
    });

    expect(screen.getByRole("spinbutton")).toHaveValue(2);
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe(
      "2",
    );
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
