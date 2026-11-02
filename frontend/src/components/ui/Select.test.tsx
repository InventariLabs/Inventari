import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { Select } from "@/components/ui/Select";
import { withLanguage } from "@/test/mocks/i18n";

const options = [
  { id: "opt1", name: "Option 1" },
  { id: "opt2", name: "Option 2" },
  { id: "opt3", name: "Option 3" },
];

describe("Select", () => {
  it("renders placeholder when no value selected", () => {
    render(
      <Select
        options={options}
        value=""
        onChange={vi.fn()}
        placeholder="Pick one"
      />,
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getByText("Pick one")).toBeInTheDocument();
  });

  it("renders all options when open", async () => {
    render(<Select options={options} value="" onChange={vi.fn()} />);
    await userEvent.setup().click(screen.getByRole("combobox"));
    options.forEach((opt) => {
      expect(
        screen.getByRole("option", { name: opt.name }),
      ).toBeInTheDocument();
    });
  });

  it("shows selected option label in trigger", () => {
    render(<Select options={options} value="opt2" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox")).toHaveTextContent("Option 2");
  });

  /**
   * The box used to appear only alongside a label, so `wrapperClassName` was
   * accepted, type-checked and thrown away on every unlabelled call site —
   * the same defect NativeSelect already fixed and documented.
   */
  it("renders its box with no label, so wrapperClassName lands somewhere", () => {
    render(
      <Select
        options={options}
        value=""
        onChange={vi.fn()}
        aria-label="Filter"
        wrapperClassName="w-fit"
      />,
    );
    const trigger = screen.getByRole("combobox");

    expect(trigger.closest(".w-fit")).not.toBeNull();
  });

  it("calls onChange when option is clicked", async () => {
    const user = userEvent.setup();
    const handleChange = vi.fn();
    render(<Select options={options} value="" onChange={handleChange} />);
    await user.click(screen.getByRole("combobox"));
    await user.click(screen.getByRole("option", { name: "Option 1" }));
    expect(handleChange).toHaveBeenCalledWith("opt1");
  });

  it("displays error state", () => {
    render(
      <Select options={options} value="" onChange={vi.fn()} error="Required" />,
    );
    expect(screen.getByText("Required")).toBeInTheDocument();
    // Same error border as Input/NativeSelect (UI_GUIDELINES §2.10).
    expect(screen.getByRole("combobox")).toHaveClass("border-red-500");
  });

  it("keeps a neutral border and background when filled (§2.10)", () => {
    render(<Select options={options} value="opt2" onChange={vi.fn()} />);
    const trigger = screen.getByRole("combobox");
    // Filled is not a state — only error and focus may tint the frame.
    expect(trigger).toHaveClass("border-border");
    const classes = trigger.className.split(/\s+/);
    expect(classes).not.toContain("border-primary-500");
    expect(classes).not.toContain("bg-primary-50");
  });
});

/**
 * The placeholder used to be an English literal in a default parameter
 * (`placeholder = "Select…"`) — the same shape removed from
 * ConfirmDialog. It surfaced on the public attestation page, where every
 * other word was translated.
 *
 * The check reads the placeholder in a language that is not English: the
 * English catalogue says "Select…" too, so comparing the rendered text with
 * the literal in English passes whichever of the two is rendering.
 */
describe("Select placeholder fallback", () => {
  it("uses the translated placeholder instead of an English literal", async () => {
    await withLanguage("pl", async () => {
      render(<Select options={options} value="" onChange={vi.fn()} />);

      const trigger = screen.getByRole("combobox");
      expect(trigger).toHaveTextContent("Wybierz…");
      expect(trigger).not.toHaveTextContent("Select…");
    });
  });
});
