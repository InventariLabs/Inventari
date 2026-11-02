import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "@/test/utils";
import InviteLinkDialog from "./InviteLinkDialog";

/**
 * The hint used to warn "there will be no second chance to copy it" while
 * the invitation's own row menu offered Copy link and the API kept
 * returning the code for as long as the invitation was pending — so an
 * administrator who believed it pasted the link into a note or a chat,
 * which is the careless keeping the warning looked like it guarded
 * against. The sentence now names the recovery that exists, and this test
 * holds that shape: the old claim stays unread, the promise of a second
 * copy stays on the screen, and the button delivers it.
 */

const writeText = vi.fn().mockResolvedValue(undefined);

const stubClipboard = (value: unknown) =>
  Object.defineProperty(navigator, "clipboard", {
    value,
    configurable: true,
  });

beforeAll(() => {
  stubClipboard({ writeText });
});

afterEach(() => {
  stubClipboard({ writeText });
  writeText.mockClear();
});

function renderDialog() {
  return renderWithProviders(
    <InviteLinkDialog
      email="kolega@example.com"
      link="https://app.example.com/register?code=abc123"
      onClose={vi.fn()}
    />,
  );
}

describe("InviteLinkDialog", () => {
  it("offers the copy again instead of claiming there is no second chance", () => {
    renderDialog();

    expect(
      screen.getByText(/while the invitation is pending/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/no second chance/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /copy link/i }),
    ).toBeInTheDocument();
  });

  it("copies the link when the reader asks for the second copy", async () => {
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        "https://app.example.com/register?code=abc123",
      ),
    );
  });

  it("says the link can be carried by hand when the copy does not land", async () => {
    // This organization sends no mail, so the link is the only way to a
    // second user — a copy that did not land has to point at the value
    // rather than change the button and say nothing.
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });

    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));

    expect(
      await screen.findByTestId("copy-link-manual-hint"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^copied$/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("https://app.example.com/register?code=abc123"),
    ).toBeInTheDocument();
  });
});
