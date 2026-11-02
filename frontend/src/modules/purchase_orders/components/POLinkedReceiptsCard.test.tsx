import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { POLinkedReceiptsCard } from "./POLinkedReceiptsCard";

describe("POLinkedReceiptsCard", () => {
  it("does not say no receipts exist when the read failed", async () => {
    const onRetry = vi.fn();
    renderWithProviders(
      <POLinkedReceiptsCard
        poId="po-1"
        receiptCount={0}
        isError
        onRetry={onRetry}
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/no receipts/i)).toBeNull();
    await userEvent.click(screen.getByRole("button"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("still says so when there really are none", () => {
    renderWithProviders(<POLinkedReceiptsCard poId="po-1" receiptCount={0} />);
    expect(screen.getByText(/no receipts/i)).toBeInTheDocument();
  });
});
