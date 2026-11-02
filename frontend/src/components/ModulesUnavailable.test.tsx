import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ModulesUnavailable from "./ModulesUnavailable";

describe("ModulesUnavailable", () => {
  it("asks again when the reader presses Try again, and holds the button while it waits", async () => {
    let finish: () => void = () => {};
    const onRetry = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<ModulesUnavailable onRetry={onRetry} />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The module list could not be read",
    );

    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button")).toBeDisabled();

    await act(async () => finish());
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });
});
