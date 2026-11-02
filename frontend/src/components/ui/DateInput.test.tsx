import { render, screen, fireEvent, within } from "@/test/utils";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DateInput } from "./DateInput";

/**
 * One date field for the whole app. The native `input[type=date]` it
 * replaces formatted itself from the browser's locale rather than the app's,
 * forced a light colour scheme, and its "Today" ran through `toISOString()`,
 * which lands on yesterday between midnight and 02:00 local time.
 */

/** jsdom answers "phone" to every media query; the popover is the desktop branch. */
let originalMatchMedia: typeof window.matchMedia | undefined;
function answerDesktop() {
  originalMatchMedia = window.matchMedia;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("DateInput", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // 00:30 local time on 15 Aug 2026 — where a UTC-based "today" slips a day
    vi.setSystemTime(new Date(2026, 7, 15, 0, 30));
  });

  afterEach(() => {
    vi.useRealTimers();
    if (originalMatchMedia) window.matchMedia = originalMatchMedia;
    originalMatchMedia = undefined;
  });

  it("shows the date formatted for the interface language, not the browser", () => {
    render(<DateInput value="2026-09-08" onChange={vi.fn()} />);

    // en-US test locale → September, not 08.09
    expect(screen.getByRole("combobox")).toHaveTextContent(/9\/8\/2026|Sep/);
  });

  it("paints the selected day on a fill white text clears 4.5:1 on", () => {
    render(<DateInput value="2026-08-15" onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("combobox"));

    const day = screen
      .getByRole("dialog")
      .querySelector('[aria-selected="true"]');
    expect(day).toHaveClass("bg-primary-700", "text-white");
    expect(day).not.toHaveClass("bg-primary-500");
  });

  it.each([
    ["a desktop popover", true],
    ["a phone sheet", false],
  ])(
    "opens %s above a nested sheet that holds the field",
    (_branch, desktop) => {
      if (desktop) answerDesktop();
      render(<DateInput value="" onChange={vi.fn()} />);

      fireEvent.click(screen.getByRole("combobox"));
      // The lot-and-expiry question is a nested sheet (--z-modal-nested);
      // a calendar on the standard modal tier painted under its backdrop,
      // and a click on a day closed the question instead.
      const dialog = screen.getByRole("dialog");
      const layered = dialog.closest<HTMLElement>('[style*="z-index"]');
      expect(layered?.style.zIndex).toBe("var(--z-confirm)");
    },
  );

  it("opens a dialog and closes it with Escape", () => {
    render(<DateInput value="" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("takes only the room the window leaves and scrolls inside it", () => {
    answerDesktop();
    render(<DateInput value="" onChange={vi.fn()} presets={["plus6Months"]} />);

    fireEvent.click(screen.getByRole("combobox"));
    // jsdom has no layout and Radix sets the variable from a measurement, so
    // this pins the rule the screen follows. Without the cap the panel ran
    // 48px above the window at 1280x577 and cut off the shortcut row, which
    // nothing could scroll back into view.
    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain(
      "max-h-[var(--radix-popover-content-available-height)]",
    );
    expect(dialog.className).toContain("overflow-y-auto");
  });

  it("picks a day from the grid", () => {
    const onChange = vi.fn();
    render(<DateInput value="2026-08-15" onChange={onChange} />);

    fireEvent.click(screen.getByRole("combobox"));
    const grid = screen.getByRole("grid");
    fireEvent.click(
      within(grid).getByRole("button", { name: /August 20, 2026/i }),
    );

    expect(onChange).toHaveBeenCalledWith("2026-08-20");
  });

  it("puts the keyboard in the calendar as soon as it opens", () => {
    // The panel opened with focus on the first preset button, so the arrow
    // keys did nothing until the user tabbed into the grid — the field read
    // as keyboard-hostile even though the grid handles arrows fine.
    render(<DateInput value="2026-08-15" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));

    expect(screen.getByRole("grid")).toHaveFocus();
  });

  it("moves the focused day with the arrow keys and picks it with Enter", () => {
    const onChange = vi.fn();
    render(<DateInput value="2026-08-15" onChange={onChange} />);

    fireEvent.click(screen.getByRole("combobox"));
    const grid = screen.getByRole("grid");

    fireEvent.keyDown(grid, { key: "ArrowRight" });
    fireEvent.keyDown(grid, { key: "ArrowDown" });
    fireEvent.keyDown(grid, { key: "Enter" });

    // one day right, one week down
    expect(onChange).toHaveBeenCalledWith("2026-08-23");
  });

  it("changes month with PageDown", () => {
    render(<DateInput value="2026-08-15" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));
    const grid = screen.getByRole("grid");
    fireEvent.keyDown(grid, { key: "PageDown" });

    expect(screen.getByRole("dialog")).toHaveTextContent(/September|wrze/i);
  });

  it("reads today from the local clock, not from UTC", () => {
    const onChange = vi.fn();
    render(<DateInput value="" onChange={onChange} presets={["today"]} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("button", { name: /today|dziś/i }));

    // 00:30 on the 15th is still the 15th, however UTC sees it
    expect(onChange).toHaveBeenCalledWith("2026-08-15");
  });

  it("offers the presets the field asks for, in the order given", () => {
    render(
      <DateInput
        value=""
        onChange={vi.fn()}
        presets={["today", "plus1Week", "plus1Month"]}
      />,
    );

    fireEvent.click(screen.getByRole("combobox"));
    const dialog = screen.getByRole("dialog");
    const presets = within(dialog).getAllByTestId("date-preset");

    expect(presets).toHaveLength(3);
  });

  it("jumps forward by a relative preset", () => {
    const onChange = vi.fn();
    render(<DateInput value="" onChange={onChange} presets={["plus1Week"]} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getAllByTestId("date-preset")[0]);

    expect(onChange).toHaveBeenCalledWith("2026-08-22");
  });

  it("can be cleared when the field is not required", () => {
    const onChange = vi.fn();
    render(<DateInput value="2026-08-15" onChange={onChange} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("button", { name: /clear|wyczyść/i }));

    expect(onChange).toHaveBeenCalledWith("");
  });
  it("renders no shortcut bar when the field asks for none", () => {
    render(<DateInput value="" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));
    const dialog = screen.getByRole("dialog");
    // The default used to be `["today"]`, so every date field in the app grew
    // a bar offering the one date already sitting on the open grid.
    expect(within(dialog).queryAllByTestId("date-preset")).toHaveLength(0);
  });

  it("jumps three years ahead in one click", () => {
    const onChange = vi.fn();
    render(<DateInput value="" onChange={onChange} presets={["plus3Years"]} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getAllByTestId("date-preset")[0]);

    expect(onChange).toHaveBeenCalledWith("2029-08-15");
  });

  it("moves a whole year per click in the panel header", () => {
    render(<DateInput value="2026-08-15" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));
    const dialog = screen.getByRole("dialog");
    const grid = within(dialog).getByRole("grid");
    const startLabel = grid.getAttribute("aria-label");

    // Reaching August 2029 through the month chevron takes 36 clicks; this is
    // the same distance in three.

    for (let i = 0; i < 3; i++) {
      fireEvent.click(
        within(dialog).getByRole("button", { name: /next year/i }),
      );
    }
    expect(grid.getAttribute("aria-label")).not.toBe(startLabel);
    expect(grid.getAttribute("aria-label")).toMatch(/2029/);

    fireEvent.click(
      within(dialog).getByRole("button", { name: /previous year/i }),
    );
    expect(grid.getAttribute("aria-label")).toMatch(/2028/);
  });

  it.each([
    ["ArrowLeft", "2026-08-14"],
    ["ArrowUp", "2026-08-08"],
    ["Home", "2026-08-01"],
    ["End", "2026-08-31"],
    ["PageUp", "2026-07-15"],
  ])(
    "moves the focused day on %s so Enter picks %s, not the day the grid opened on",
    (key, expected) => {
      const onChange = vi.fn();
      render(<DateInput value="2026-08-15" onChange={onChange} />);

      fireEvent.click(screen.getByRole("combobox"));
      const grid = screen.getByRole("grid");
      fireEvent.keyDown(grid, { key });
      fireEvent.keyDown(grid, { key: "Enter" });

      expect(onChange).toHaveBeenCalledWith(expected);
    },
  );

  it("steps to the next month with the header chevron", () => {
    render(<DateInput value="2026-08-15" onChange={vi.fn()} />);

    fireEvent.click(screen.getByRole("combobox"));
    const grid = screen.getByRole("grid");
    expect(grid.getAttribute("aria-label")).toMatch(/August 2026/);

    fireEvent.click(screen.getByRole("button", { name: /next month/i }));

    expect(grid.getAttribute("aria-label")).toMatch(/September 2026/);
  });

  it("jumps two years ahead with the two-year preset", () => {
    const onChange = vi.fn();
    render(<DateInput value="" onChange={onChange} presets={["plus2Years"]} />);

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getAllByTestId("date-preset")[0]);

    expect(onChange).toHaveBeenCalledWith("2028-08-15");
  });

  /**
   * The popover's trigger props went to the field's wrapper `div` — the box
   * around the label and the button — so `aria-expanded` sat on an element
   * that may not carry it, and a required field put `aria-required` on a
   * button, where it means nothing. Both are critical in axe. The trigger is
   * a combobox, the role that carries both, named by the field's label.
   */
  it.each([
    ["desktop", true],
    ["phone", false],
  ])(
    "states the popup and the requirement on the trigger on a %s",
    (_, desktop) => {
      if (desktop) answerDesktop();
      render(<DateInput label="Due" required value="" onChange={vi.fn()} />);

      const trigger = screen.getByRole("combobox", { name: /Due/ });
      expect(trigger).toHaveAttribute("aria-required", "true");
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(trigger.parentElement).not.toHaveAttribute("aria-expanded");

      fireEvent.click(trigger);
      expect(trigger).toHaveAttribute("aria-expanded", "true");
      // A combobox names the popup it controls; the bottom sheet had no id
      // to name, so on a phone the trigger pointed nowhere.
      const dialog = screen.getByRole("dialog");
      expect(dialog.id).not.toBe("");
      expect(trigger).toHaveAttribute("aria-controls", dialog.id);
    },
  );
});
