import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import RecipeMarkdownEditor from "./RecipeMarkdownEditor";

/** Holds the text the form would, so the editor is exercised as controlled. */
function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <RecipeMarkdownEditor value={value} onChange={setValue} />;
}

const box = () =>
  screen.getByRole("textbox", { name: "Instructions" }) as HTMLTextAreaElement;

const select = (start: number, end = start) => {
  box().focus();
  box().setSelectionRange(start, end);
};

/**
 * The instructions editor writes Markdown around the selection. Wrapping the
 * wrong range, or prefixing the wrong line, corrupts text the cook typed.
 */
describe("RecipeMarkdownEditor", () => {
  it("passes typing straight through", () => {
    render(<Harness />);
    fireEvent.change(box(), { target: { value: "Mix." } });
    expect(box()).toHaveValue("Mix.");
  });

  it("wraps the selection in bold markers", () => {
    render(<Harness initial="Add salt now" />);
    select(4, 8);
    fireEvent.click(screen.getByRole("button", { name: "Bold" }));
    expect(box()).toHaveValue("Add **salt** now");
  });

  it("inserts a placeholder between the markers when nothing is selected", () => {
    render(<Harness initial="Add " />);
    select(4);
    fireEvent.click(screen.getByRole("button", { name: "Italic" }));
    expect(box()).toHaveValue("Add *text*");
  });

  it.each([
    ["Heading", "## "],
    ["Bullet list", "- "],
    ["Numbered list", "1. "],
  ])(
    "%s prefixes the line the cursor is on, not the first one",
    (name, prefix) => {
      render(<Harness initial={"first\nsecond line"} />);
      select(9);
      fireEvent.click(screen.getByRole("button", { name }));
      expect(box()).toHaveValue(`first\n${prefix}second line`);
    },
  );

  it("prefixes the first line when the cursor is on it", () => {
    render(<Harness initial={"first\nsecond"} />);
    select(2);
    fireEvent.click(screen.getByRole("button", { name: "Bullet list" }));
    expect(box()).toHaveValue("- first\nsecond");
  });

  it("previews the rendered Markdown and hides the formatting buttons", () => {
    render(<Harness initial="Use **plenty** of salt" />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByText("plenty").tagName).toBe("STRONG");
    expect(
      screen.queryByRole("button", { name: "Bold" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(box()).toHaveValue("Use **plenty** of salt");
  });

  it("says so when there is nothing to preview", () => {
    render(<Harness initial="   " />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(screen.getByText(/No instructions yet/)).toBeInTheDocument();
  });

  it("strips markup that could run script from the preview", () => {
    render(<Harness initial={"hello <script>alert(1)</script>"} />);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(document.querySelector("script")).toBeNull();
  });
});
