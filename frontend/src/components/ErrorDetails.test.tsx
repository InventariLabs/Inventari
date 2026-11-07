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

function reportAt(address: string): string {
  const href = `${window.location.origin}${address}`;
  vi.stubGlobal("location", { ...window.location, href });
  render(<ErrorDetails error={new Error("planted")} />);
  return screen.getByLabelText("Error details").textContent ?? "";
}

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

  // The pages an e-mailed link opens carry that link's live token in their
  // address, and the report is pasted wherever the reader files bugs — for a
  // self-hosted install, often a public issue tracker.
  it.each([
    [
      "a password reset link",
      "/reset-password/planted-secret",
      "/reset-password/redacted",
    ],
    ["an old invitation link", "/join/planted-secret", "/join/redacted"],
    ["an invitation link", "/join?code=planted-secret", "/join?code=redacted"],
    [
      "a registration link",
      "/register?token=planted-secret&invite=planted-secret",
      "/register?token=redacted&invite=redacted",
    ],
    [
      "an attestation link",
      "/public/attestation/planted-secret",
      "/public/attestation/redacted",
    ],
  ])("keeps the token of %s out of the report", (_link, address, reported) => {
    const shown = reportAt(address);

    expect(shown).not.toContain("planted-secret");
    expect(shown).toContain(`${window.location.origin}${reported}`);
  });

  it("keeps an ordinary address whole", () => {
    const address = "/warehouse/documents/abc?type=receipt&page=2";

    expect(reportAt(address)).toContain(`${window.location.origin}${address}`);
  });

  it("tells the reader to copy by hand when the browser has no clipboard", async () => {
    vi.stubGlobal("navigator", {});
    render(<ErrorDetails error={new Error("planted")} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy details" }));

    expect(await screen.findByRole("status")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copied" })).toBeNull();
  });
});
