import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, type AxiosResponse } from "axios";
import { describe, expect, it, vi } from "vitest";
import { LotStatusDialog } from "./LotStatusDialog";

/**
 * A status change the server failed without a reason used to read "The
 * action could not be completed." — the sentence every dialog falls back to,
 * which says nothing about which change it was or whether it happened.
 */
describe("LotStatusDialog", () => {
  it("names the status change when the server fails without a reason", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn(() =>
      Promise.reject(
        new AxiosError("boom", "ERR_BAD_RESPONSE", undefined, undefined, {
          status: 500,
          data: { detail: "Internal Server Error" },
        } as AxiosResponse),
      ),
    );
    render(
      <LotStatusDialog
        request={{ lotId: "lot-1", lotName: "L-2611", status: "quarantined" }}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText(/Why/), "Supplier notice");
    await user.click(screen.getByRole("button", { name: "Change status" }));

    expect(onConfirm).toHaveBeenCalledWith("Supplier notice");
    expect(
      await screen.findByText("Could not change the batch status"),
    ).toBeInTheDocument();
    // The question stays, with the reason as typed, for a second try.
    expect(screen.getByLabelText(/Why/)).toHaveValue("Supplier notice");
  });
});
