/**
 * The products list's bulk delete asks for a reason once, in the dialog the
 * single delete uses. Its `onBulkDelete` runs the action and keeps the
 * promise, so a refused delete does not close the dialog with no word, and the
 * console gets no unhandled rejection.
 */
import { AxiosError, type AxiosResponse } from "axios";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { describe, expect, it, vi } from "vitest";
import { ItemsPageDialogs } from "./ItemsPageDialogs";

function renderDialogs(onBulkDelete: () => Promise<void>) {
  return render(
    <ItemsPageDialogs
      deleteReasonItem={null}
      onDelete={vi.fn()}
      onDeleteCancel={vi.fn()}
      bulkDeleteIds={["a", "b"]}
      onBulkDelete={onBulkDelete}
      onBulkDeleteCancel={vi.fn()}
      consumeDialogItem={null}
      onConsume={vi.fn()}
      onConsumeCancel={vi.fn()}
    />,
  );
}

function chooseReasonAndDelete() {
  fireEvent.change(screen.getByTestId("deletion-reason"), {
    target: { value: "EXPIRED" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Delete" }));
}

describe("ItemsPageDialogs — the bulk delete", () => {
  it("asks the question about the whole selection and waits for a reason", () => {
    renderDialogs(() => Promise.resolve());

    expect(screen.getByText("Delete 2 selected products?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });

  it("stays open with the reason when the action is refused", async () => {
    renderDialogs(() =>
      Promise.reject(
        new AxiosError("conflict", "ERR_BAD_REQUEST", undefined, undefined, {
          status: 409,
          data: { detail: "Product is locked" },
        } as AxiosResponse),
      ),
    );
    chooseReasonAndDelete();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Product is locked",
    );
    expect(screen.getByText("Delete 2 selected products?")).toBeInTheDocument();
  });

  it("hands the chosen reason to the action once", async () => {
    const onBulkDelete = vi.fn(() => Promise.resolve());
    renderDialogs(onBulkDelete);
    chooseReasonAndDelete();

    await waitFor(() => expect(onBulkDelete).toHaveBeenCalledTimes(1));
    expect(onBulkDelete).toHaveBeenCalledWith(["a", "b"], "EXPIRED", "");
  });
});
