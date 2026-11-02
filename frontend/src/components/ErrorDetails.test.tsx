/**
 * The hand-off from a crashed screen to a bug report. Nothing on a
 * self-hosted install receives the error, so the text on screen and the
 * button that copies it are the whole path.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ErrorDetails from "./ErrorDetails";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ErrorDetails", () => {
  it("shows the failure and the page, and copies exactly what it shows", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    render(<ErrorDetails error={new Error("planted: the screen broke")} />);

    const shown = screen.getByLabelText("Error details").textContent ?? "";
    expect(shown).toContain("planted: the screen broke");
    expect(shown).toContain(window.location.href);

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(shown));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  });

  it("tells the reader to copy by hand when the browser has no clipboard", async () => {
    vi.stubGlobal("navigator", {});
    render(<ErrorDetails error={new Error("planted")} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });
});
