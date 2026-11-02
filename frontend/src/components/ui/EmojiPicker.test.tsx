import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { EmojiPicker } from "@/components/ui/EmojiPicker";

function openPicker() {
  return userEvent.click(screen.getByRole("button", { name: "Symbol" }));
}

describe("EmojiPicker", () => {
  it("shows the current emoji on the trigger and 'Auto' text when none is chosen", () => {
    const { rerender } = render(
      <EmojiPicker value={null} onChange={vi.fn()} />,
    );
    expect(screen.getByText("Auto (based on name)")).toBeInTheDocument();

    rerender(<EmojiPicker value="🍎" onChange={vi.fn()} />);
    expect(screen.queryByText("Auto (based on name)")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Symbol" })).toHaveTextContent(
      "🍎",
    );
  });

  it("reports the clicked emoji from the category grid and closes the popover", async () => {
    const onChange = vi.fn();
    render(<EmojiPicker value={null} onChange={onChange} />);
    await openPicker();

    expect(screen.getByText("Smileys")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "😀" }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith("😀");
    expect(
      screen.queryByRole("textbox", { name: "Search emoji…" }),
    ).not.toBeInTheDocument();
  });

  it("filters by keyword and picks from the search results", async () => {
    const onChange = vi.fn();
    render(<EmojiPicker value={null} onChange={onChange} />);
    await openPicker();

    await userEvent.type(
      screen.getByRole("textbox", { name: "Search emoji…" }),
      "banana",
    );

    // Category headings disappear while a search is active.
    expect(screen.queryByText("Smileys")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "😀" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "🍌" }));
    expect(onChange).toHaveBeenCalledExactlyOnceWith("🍌");
  });

  it("says so when no emoji matches the search", async () => {
    render(<EmojiPicker value={null} onChange={vi.fn()} />);
    await openPicker();

    await userEvent.type(
      screen.getByRole("textbox", { name: "Search emoji…" }),
      "zzzznotanemoji",
    );

    expect(screen.getByText("No emoji found")).toBeInTheDocument();
  });

  it("clears the search when the popover is closed and reopened", async () => {
    render(<EmojiPicker value={null} onChange={vi.fn()} />);
    await openPicker();
    await userEvent.type(
      screen.getByRole("textbox", { name: "Search emoji…" }),
      "banana",
    );

    await userEvent.keyboard("{Escape}");
    expect(
      screen.queryByRole("textbox", { name: "Search emoji…" }),
    ).not.toBeInTheDocument();

    await openPicker();
    expect(screen.getByRole("textbox", { name: "Search emoji…" })).toHaveValue(
      "",
    );
    expect(screen.getByText("Smileys")).toBeInTheDocument();
  });

  it("resets to automatic (null) with the Auto button", async () => {
    function Harness() {
      const [v, setV] = useState<string | null>("🍎");
      return (
        <>
          <EmojiPicker value={v} onChange={setV} />
          <output data-testid="value">{String(v)}</output>
        </>
      );
    }
    render(<Harness />);
    expect(screen.getByTestId("value")).toHaveTextContent("🍎");
    await openPicker();

    // While the popover is open the trigger is aria-hidden, so this is the
    // reset button inside the popover.
    await userEvent.click(
      screen.getByRole("button", { name: "Auto (based on name)" }),
    );

    expect(screen.getByTestId("value")).toHaveTextContent("null");
    expect(screen.getByText("Auto (based on name)")).toBeInTheDocument();
  });
});
