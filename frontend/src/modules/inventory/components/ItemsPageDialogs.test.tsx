/**
 * The products list's plain confirmation answers through `useConfirmDialog`:
 * its `onConfirm` used to run the action, drop the promise and close the
 * question. A refused bulk delete then closed the dialog with no word, the
 * rows stayed, and the console got an unhandled rejection.
 */
import { AxiosError, type AxiosResponse } from "axios";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { describe, expect, it, vi } from "vitest";
import { useConfirmDialog } from "@/hooks/useConfirmDialog";
import { ItemsPageDialogs } from "./ItemsPageDialogs";

function Harness({ onConfirm }: { onConfirm: () => Promise<void> }) {
  const { dialogState, showConfirm, closeDialog } = useConfirmDialog();
  return (
    <>
      <button
        onClick={() =>
          showConfirm({
            title: "Delete 2 selected products?",
            message: "The products go to the archive and can be restored.",
            confirmText: "Delete",
            onConfirm,
          })
        }
      >
        open
      </button>
      <ItemsPageDialogs
        dialogState={dialogState}
        closeDialog={closeDialog}
        deleteReasonItem={null}
        onDelete={vi.fn()}
        onDeleteCancel={vi.fn()}
        consumeDialogItem={null}
        onConsume={vi.fn()}
        onConsumeCancel={vi.fn()}
      />
    </>
  );
}

describe("ItemsPageDialogs — the plain confirmation", () => {
  it("stays open with the reason when the action is refused", async () => {
    render(
      <Harness
        onConfirm={() =>
          Promise.reject(
            new AxiosError(
              "conflict",
              "ERR_BAD_REQUEST",
              undefined,
              undefined,
              {
                status: 409,
                data: { detail: "Product is locked" },
              } as AxiosResponse,
            ),
          )
        }
      />,
    );
    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Product is locked",
    );
    expect(screen.getByText("Delete 2 selected products?")).toBeInTheDocument();
  });

  it("closes once the action has gone through", async () => {
    const onConfirm = vi.fn(() => Promise.resolve());
    render(<Harness onConfirm={onConfirm} />);
    fireEvent.click(screen.getByText("open"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Delete 2 selected products?"),
      ).not.toBeInTheDocument(),
    );
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
