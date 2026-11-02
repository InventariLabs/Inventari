import { fireEvent } from "@testing-library/react";
import { vi } from "vitest";

/**
 * The gap a scanner puts between two of its keys.
 *
 * `useScannerInput` reads a burst as a scan when each key follows the last
 * within 50 ms (30 ms for a code short enough to be mistaken for a person's
 * typing), so this is well inside both bounds.
 */
const SCANNER_KEY_GAP_MS = 5;

/**
 * Where the scanner's clock stood when its last burst ended, while the test
 * has not yet yielded since.
 */
let lastBurstEndedAt: number | null = null;

/**
 * A person's pause before the trigger: longer than the 50 ms gap that would
 * still join a key to the burst after it.
 */
const PERSON_PAUSE_MS = 80;

/** Where the pause `pauseBeforeScan` asked for ends, on the scanner's clock. */
let pauseEndsAt: number | null = null;

/**
 * Run `send` with the clock held still at the real time and moved
 * `SCANNER_KEY_GAP_MS` on for every `tick`.
 *
 * The hook times a burst by `Date.now()` between keydowns, and a test's own
 * keys take however long the machine makes them take: on a loaded host a
 * burst of thirteen events straddles the 50 ms rule and the code arrives in
 * pieces — a green branch failing a test it does not touch. Here the test
 * owns the clock: it does not move while React handles a key, so the gap
 * between two keys is exactly what the test says, whatever the host is
 * doing. It starts at the real time, so a pause the test takes before the
 * burst is still a pause. Bursts sent one after another with no await
 * between them — a scanner's double read — follow each other at the
 * scanner's pace too, however long the first took the host to handle.
 */
function atScannerPace<T>(send: (tick: () => void) => T): T {
  const start = lastBurstEndedAt ?? Date.now();
  let now = Math.max(start, pauseEndsAt ?? start);
  pauseEndsAt = null;
  const clock = vi.spyOn(Date, "now").mockImplementation(() => now);
  try {
    return send(() => {
      now += SCANNER_KEY_GAP_MS;
    });
  } finally {
    clock.mockRestore();
    lastBurstEndedAt = now;
    // The first await after the burst is a pause, and the next burst starts
    // from the real time again.
    queueMicrotask(() => {
      lastBurstEndedAt = null;
    });
  }
}

/**
 * A person's pause between the keys the test has sent so far and the next
 * burst. The burst starts that much later on the scanner's clock instead of
 * after a real wait: a wall-clock pause is only as long as the host keeps it,
 * and this one is the same on any host and costs the run nothing.
 */
export function pauseBeforeScan() {
  pauseEndsAt = (lastBurstEndedAt ?? Date.now()) + PERSON_PAUSE_MS;
}

/**
 * A keyboard-wedge barcode scanner: the code's characters and an Enter, sent
 * at once to whatever has the focus (the page itself when nothing does).
 */
export function scanWithHardwareScanner(
  code: string,
  target: Element = document.activeElement ?? document.body,
) {
  return atScannerPace((tick) => {
    for (const key of code) {
      tick();
      fireEvent.keyDown(target, { key });
    }
    tick();
    return fireEvent.keyDown(target, { key: "Enter" });
  });
}

/**
 * The same scanner, with the focus in an editable field: unlike
 * `scanWithHardwareScanner`, every character also lands in the field, as a
 * browser would put it there. `terminator` closes the burst — Tab, for a
 * screen that reads the shelf code before the product.
 */
export function scanIntoField(
  code: string,
  field: HTMLInputElement,
  terminator = "Enter",
) {
  return atScannerPace((tick) => {
    for (const key of code) {
      tick();
      fireEvent.keyDown(field, { key });
      fireEvent.change(field, { target: { value: field.value + key } });
    }
    tick();
    return fireEvent.keyDown(field, { key: terminator });
  });
}

/**
 * An Android scanning keyboard with the focus in `field`: the whole code as
 * one text insertion, then Enter.
 */
export function insertScanIntoField(code: string, field: HTMLInputElement) {
  return atScannerPace((tick) => {
    tick();
    fireEvent.keyDown(field, { key: "Unidentified" });
    tick();
    fireEvent(
      field,
      new InputEvent("beforeinput", {
        data: code,
        inputType: "insertText",
        bubbles: true,
        cancelable: true,
      }),
    );
    tick();
    fireEvent.change(field, { target: { value: field.value + code } });
    tick();
    return fireEvent.keyDown(field, { key: "Enter" });
  });
}
