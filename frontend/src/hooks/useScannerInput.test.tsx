import { useState } from "react";
import { act, render, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  SCANNER_INPUT_ATTRIBUTE,
  SCANNER_WHOLE_ATTRIBUTE,
  SCANNER_KEEP_ATTRIBUTE,
  useScannerInput,
} from "./useScannerInput";

/** A quantity field that holds what is typed in it, as the screens' do. */
function QuantityField() {
  const [value, setValue] = useState("");
  return (
    <input
      aria-label="quantity"
      type="number"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      {...{ [SCANNER_KEEP_ATTRIBUTE]: "" }}
    />
  );
}

/** Put text into `field` the way typing does: the value, then an input event. */
function insert(field: HTMLInputElement, text: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  act(() => {
    setter.call(field, field.value + text);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Press one key on `target` the way a browser does: keydown, cancellable. */
function press(
  key: string,
  target: EventTarget = document.body,
): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
  });
  target.dispatchEvent(event);
  return event;
}

/** A wedge scanner: every character `gapMs` after the previous one. */
function burst(
  code: string,
  { gapMs = 10, target = document.body as EventTarget } = {},
) {
  for (const char of code) {
    press(char, target);
    vi.advanceTimersByTime(gapMs);
  }
}

describe("useScannerInput", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("emits a burst ending with Enter once and keeps the Enter from the page", () => {
    const onScan = vi.fn();
    const pageSaw = vi.fn();
    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter") pageSaw();
    });
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457");
    const enter = press("Enter");

    expect(onScan).toHaveBeenCalledTimes(1);
    expect(onScan).toHaveBeenCalledWith("5901234123457");
    expect(enter.defaultPrevented).toBe(true);
    expect(pageSaw).not.toHaveBeenCalled();
  });

  it("hands over the code a QR sticker's address carries", () => {
    // A 2D hardware scanner types the whole address the QR holds; the
    // stickers printed so far open the app's own scan page.
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("https://wh.example.test/labels/scan/A-02-01");
    press("Enter");

    expect(onScan).toHaveBeenCalledWith("A-02-01");
  });

  it("counts the same code read twice within 300 ms once, and swallows both Enters", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457");
    press("Enter");
    vi.advanceTimersByTime(60);
    burst("5901234123457");
    const second = press("Enter");

    expect(onScan).toHaveBeenCalledTimes(1);
    expect(second.defaultPrevented).toBe(true);
  });

  it("emits the same code again once 300 ms have passed, and a different code at once", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457");
    press("Enter");
    burst("4006381333931");
    press("Enter");
    vi.advanceTimersByTime(300);
    burst("4006381333931");
    press("Enter");

    expect(onScan.mock.calls).toEqual([
      ["5901234123457"],
      ["4006381333931"],
      ["4006381333931"],
    ]);
  });

  it("accepts Tab as the terminator", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("LOC-A1-03");
    const tab = press("Tab");

    expect(onScan).toHaveBeenCalledWith("LOC-A1-03");
    expect(tab.defaultPrevented).toBe(true);
  });

  it("emits nothing for keys typed 150 ms apart, and lets the Enter through", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457", { gapMs: 150 });
    const enter = press("Enter");

    expect(onScan).not.toHaveBeenCalled();
    expect(enter.defaultPrevented).toBe(false);
  });

  it.each([
    ["A", "Enter"],
    ["A", "Tab"],
    ["AA", "Enter"],
    ["W2", "Tab"],
    ["001", "Enter"],
  ])(
    "takes the short shelf code %s a warehouse template gives a zone, closed by %s",
    (code, terminator) => {
      // A zone's code under the default template is one letter; a scanner
      // sends it as fast as any other.
      const onScan = vi.fn();
      renderHook(() => useScannerInput(onScan));

      burst(code, { gapMs: 5 });
      const end = press(terminator);

      expect(onScan).toHaveBeenCalledWith(code);
      expect(end.defaultPrevented).toBe(true);
    },
  );

  it.each(["AA-01", "LOC-UK71", "A"])(
    "reads %s whole from a scanner that holds Shift for every capital",
    (code) => {
      // A USB scanner is a keyboard: a capital is Shift and the letter.
      const onScan = vi.fn();
      renderHook(() => useScannerInput(onScan));

      for (const char of code) {
        if (char !== char.toLowerCase()) press("Shift");
        press(char);
        vi.advanceTimersByTime(5);
      }
      press("Enter");

      expect(onScan.mock.calls).toEqual([[code]]);
    },
  );

  it("emits nothing for a short code typed at a quick person's pace", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("12", { gapMs: 40 });
    const enter = press("Enter");

    expect(onScan).not.toHaveBeenCalled();
    expect(enter.defaultPrevented).toBe(false);
  });

  it("emits nothing when the Enter comes long after a fast burst", () => {
    const onScan = vi.fn();
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457");
    vi.advanceTimersByTime(500);
    press("Enter");

    expect(onScan).not.toHaveBeenCalled();
  });

  it("emits nothing for a burst while a plain text field has focus", () => {
    const onScan = vi.fn();
    const field = document.createElement("input");
    document.body.appendChild(field);
    field.focus();
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457", { target: field });
    const enter = press("Enter", field);

    expect(onScan).not.toHaveBeenCalled();
    expect(enter.defaultPrevented).toBe(false);
  });

  it("takes a burst typed into a field that opted in", () => {
    const onScan = vi.fn();
    const { getByRole } = render(
      <input aria-label="code" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />,
    );
    const field = getByRole("textbox");
    renderHook(() => useScannerInput(onScan));

    burst("5901234123457", { target: field });
    const enter = press("Enter", field);

    expect(onScan).toHaveBeenCalledWith("5901234123457");
    expect(enter.defaultPrevented).toBe(true);
  });

  it("hands over what a field holds when only the end of it came fast", () => {
    // A person typing a long code in the field pauses once; the keys after the
    // pause are a burst by the clock, and used to be emitted alone with the
    // start of the code left behind in the field.
    const onScan = vi.fn();
    const { getByRole } = render(
      <input
        aria-label="code"
        {...{ [SCANNER_INPUT_ATTRIBUTE]: "", [SCANNER_WHOLE_ATTRIBUTE]: "" }}
      />,
    );
    const field = getByRole("textbox") as HTMLInputElement;
    renderHook(() => useScannerInput(onScan));

    const code = "127.0.0.1:5673/s/LOC-AB12";
    [...code].forEach((char, index) => {
      press(char, field);
      insert(field, char);
      vi.advanceTimersByTime(index < 10 ? 120 : 10);
    });
    const enter = press("Enter", field);

    expect(onScan).toHaveBeenCalledTimes(1);
    expect(onScan).toHaveBeenCalledWith(code);
    expect(enter.defaultPrevented).toBe(true);
  });

  it("emits the burst alone from an opted-in field that holds other text", () => {
    // A search box takes a scan too, but what the person typed there first is
    // theirs, not the start of the code.
    const onScan = vi.fn();
    const { getByRole } = render(
      <input aria-label="search" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />,
    );
    const field = getByRole("textbox") as HTMLInputElement;
    renderHook(() => useScannerInput(onScan));

    [..."milk"].forEach((char) => {
      press(char, field);
      insert(field, char);
      vi.advanceTimersByTime(120);
    });
    [..."LOC-ZZ99"].forEach((char) => {
      press(char, field);
      insert(field, char);
      vi.advanceTimersByTime(5);
    });
    press("Enter", field);

    expect(onScan).toHaveBeenCalledTimes(1);
    expect(onScan).toHaveBeenCalledWith("LOC-ZZ99");
  });

  it("on an opted-in field emits a single text insertion followed by Enter", () => {
    const onScan = vi.fn();
    const { getByRole } = render(
      <input aria-label="code" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />,
    );
    const field = getByRole("textbox");
    renderHook(() => useScannerInput(onScan));

    // An Android scanning keyboard: an IME keydown that names no key, the
    // whole code as one insertion, then Enter.
    press("Unidentified", field);
    field.dispatchEvent(
      new InputEvent("beforeinput", {
        data: "5901234123457",
        inputType: "insertText",
        bubbles: true,
        cancelable: true,
      }),
    );
    vi.advanceTimersByTime(20);
    const enter = press("Enter", field);

    expect(onScan).toHaveBeenCalledTimes(1);
    expect(onScan).toHaveBeenCalledWith("5901234123457");
    expect(enter.defaultPrevented).toBe(true);
  });

  it("takes a one-letter code typed or inserted into a field that opted in", () => {
    const onScan = vi.fn();
    const { getByRole } = render(
      <input aria-label="code" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />,
    );
    const field = getByRole("textbox");
    renderHook(() => useScannerInput(onScan));

    burst("A", { gapMs: 5, target: field });
    const tab = press("Tab", field);
    vi.advanceTimersByTime(500);
    press("Unidentified", field);
    field.dispatchEvent(
      new InputEvent("beforeinput", {
        data: "B",
        inputType: "insertText",
        bubbles: true,
        cancelable: true,
      }),
    );
    vi.advanceTimersByTime(5);
    const enter = press("Enter", field);

    expect(onScan.mock.calls).toEqual([["A"], ["B"]]);
    expect(tab.defaultPrevented).toBe(true);
    expect(enter.defaultPrevented).toBe(true);
  });

  it("takes a single insertion closed by Tab when no IME keydown came first", () => {
    const onScan = vi.fn();
    const { getByRole } = render(
      <input aria-label="code" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />,
    );
    const field = getByRole("textbox");
    renderHook(() => useScannerInput(onScan));

    // A keydown elsewhere (the quantity), then the insertion into a field
    // that has seen no key of its own: the insertion names its target.
    press("2", document.body);
    field.dispatchEvent(
      new InputEvent("beforeinput", {
        data: "5901234123457",
        inputType: "insertText",
        bubbles: true,
        cancelable: true,
      }),
    );
    vi.advanceTimersByTime(20);
    const tab = press("Tab", field);

    expect(onScan).toHaveBeenCalledWith("5901234123457");
    expect(tab.defaultPrevented).toBe(true);
  });

  it("ignores a single insertion on a field that did not opt in", () => {
    const onScan = vi.fn();
    const field = document.createElement("input");
    document.body.appendChild(field);
    renderHook(() => useScannerInput(onScan));

    field.dispatchEvent(
      new InputEvent("beforeinput", {
        data: "5901234123457",
        inputType: "insertText",
        bubbles: true,
      }),
    );
    press("Enter", field);

    expect(onScan).not.toHaveBeenCalled();
  });

  it("emits nothing while disabled, and stops listening once unmounted", () => {
    const onScan = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ enabled }) => useScannerInput(onScan, { enabled }),
      { initialProps: { enabled: false } },
    );

    burst("5901234123457");
    press("Enter");
    expect(onScan).not.toHaveBeenCalled();

    rerender({ enabled: true });
    unmount();
    burst("5901234123457");
    press("Enter");
    expect(onScan).not.toHaveBeenCalled();
  });

  it("calls the latest handler without re-subscribing", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ cb }) => useScannerInput(cb), {
      initialProps: { cb: first },
    });

    rerender({ cb: second });
    burst("5901234123457");
    press("Enter");

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith("5901234123457");
  });

  describe("in a field that keeps its value", () => {
    it("takes a wedge burst and gives the field back what was typed before it", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(<QuantityField />);
      const field = getByLabelText("quantity") as HTMLInputElement;
      renderHook(() => useScannerInput(onScan));

      field.focus();
      for (const char of "20") {
        press(char, field);
        insert(field, char);
        vi.advanceTimersByTime(200);
      }
      for (const char of "5901234123457") {
        press(char, field);
        insert(field, char);
        vi.advanceTimersByTime(10);
      }
      expect(field.value).toBe("205901234123457");
      let enter!: KeyboardEvent;
      act(() => {
        enter = press("Enter", field);
      });

      expect(onScan).toHaveBeenCalledTimes(1);
      expect(onScan).toHaveBeenCalledWith("5901234123457");
      expect(enter.defaultPrevented).toBe(true);
      expect(field.value).toBe("20");
    });

    it("takes a single text insertion the same way", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(<QuantityField />);
      const field = getByLabelText("quantity") as HTMLInputElement;
      renderHook(() => useScannerInput(onScan));

      field.focus();
      for (const char of "20") {
        press(char, field);
        insert(field, char);
        vi.advanceTimersByTime(200);
      }
      press("Unidentified", field);
      field.dispatchEvent(
        new InputEvent("beforeinput", {
          data: "5901234123457",
          inputType: "insertText",
          bubbles: true,
          cancelable: true,
        }),
      );
      insert(field, "5901234123457");
      vi.advanceTimersByTime(20);
      act(() => {
        press("Enter", field);
      });

      expect(onScan).toHaveBeenCalledWith("5901234123457");
      expect(field.value).toBe("20");
    });

    it("takes a one-letter zone code and leaves the quantity as it was", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(<QuantityField />);
      const field = getByLabelText("quantity") as HTMLInputElement;
      renderHook(() => useScannerInput(onScan));

      field.focus();
      press("2", field);
      insert(field, "2");
      vi.advanceTimersByTime(200);
      press("A", field);
      insert(field, "A");
      vi.advanceTimersByTime(5);
      let enter!: KeyboardEvent;
      act(() => {
        enter = press("Enter", field);
      });

      expect(onScan).toHaveBeenCalledWith("A");
      expect(enter.defaultPrevented).toBe(true);
      expect(field.value).toBe("2");
    });

    it("leaves a digit and a quick Enter typed by hand alone", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(<QuantityField />);
      const field = getByLabelText("quantity") as HTMLInputElement;
      renderHook(() => useScannerInput(onScan));

      field.focus();
      press("5", field);
      insert(field, "5");
      vi.advanceTimersByTime(40);
      const enter = press("Enter", field);

      expect(onScan).not.toHaveBeenCalled();
      expect(enter.defaultPrevented).toBe(false);
      expect(field.value).toBe("5");
    });

    it("does not carry keys typed in one field into a code read in another", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(
        <>
          <QuantityField />
          <input aria-label="code" {...{ [SCANNER_INPUT_ATTRIBUTE]: "" }} />
        </>,
      );
      const quantity = getByLabelText("quantity") as HTMLInputElement;
      const code = getByLabelText("code");
      renderHook(() => useScannerInput(onScan));

      press("2", quantity);
      vi.advanceTimersByTime(10);
      burst("5901234123457", { target: code });
      press("Enter", code);

      expect(onScan).toHaveBeenCalledWith("5901234123457");
    });

    it("leaves a quantity typed by hand, digit by digit, alone", () => {
      const onScan = vi.fn();
      const { getByLabelText } = render(<QuantityField />);
      const field = getByLabelText("quantity") as HTMLInputElement;
      renderHook(() => useScannerInput(onScan));

      field.focus();
      for (const char of "12345") {
        const down = press(char, field);
        insert(field, char);
        expect(down.defaultPrevented).toBe(false);
        vi.advanceTimersByTime(200);
      }
      const enter = press("Enter", field);

      expect(onScan).not.toHaveBeenCalled();
      expect(enter.defaultPrevented).toBe(false);
      expect(field.value).toBe("12345");
    });
  });
});
