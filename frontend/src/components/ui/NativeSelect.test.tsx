import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { NativeSelect } from "@/components/ui/NativeSelect";

describe("NativeSelect", () => {
  it("associates the label with the select when the caller passes no id", () => {
    render(
      <NativeSelect label="Sort by">
        <option value="name">Name</option>
      </NativeSelect>,
    );
    expect(screen.getByLabelText("Sort by")).toBeInTheDocument();
  });

  it("honours an id supplied by the caller", () => {
    render(
      <NativeSelect id="sort" label="Sort by">
        <option value="name">Name</option>
      </NativeSelect>,
    );
    expect(screen.getByLabelText("Sort by")).toHaveAttribute("id", "sort");
  });

  /**
   * The box used to appear only alongside a label, so `wrapperClassName` was
   * accepted, type-checked and thrown away on every unlabelled call site.
   */
  it("renders its box with no label, so wrapperClassName lands somewhere", () => {
    render(
      <NativeSelect aria-label="Sort by" wrapperClassName="w-fit">
        <option value="name">Name</option>
      </NativeSelect>,
    );
    const select = screen.getByLabelText("Sort by");

    expect(select.tagName).toBe("SELECT");
    // The chevron below needs a positioned parent, so the wrapper is now the
    // grandparent — `closest` keeps the assertion about the box, not the depth.
    expect(select.closest(".w-fit")).not.toBeNull();
  });

  it("draws its own disclosure chevron instead of the platform arrow", () => {
    const { container } = render(
      <NativeSelect aria-label="Sort by">
        <option value="name">Name</option>
      </NativeSelect>,
    );
    const select = screen.getByLabelText("Sort by");

    // Without `appearance-none` the browser keeps drawing its own arrow next
    // to ours, and the two disagree on every platform (§2.10).
    expect(select.className.split(/\s+/)).toContain("appearance-none");
    expect(select.className.split(/\s+/)).toContain("pr-10");
    const chevron = container.querySelector("svg.lucide-chevron-down");
    expect(chevron).not.toBeNull();
    expect(chevron?.getAttribute("aria-hidden")).toBe("true");
  });
});
