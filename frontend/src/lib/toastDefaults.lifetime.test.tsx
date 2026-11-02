import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toaster, toast } from "sonner";
import {
  SUCCESS_TOAST_DURATION_MS,
  installToastDefaults,
  readingToastDuration,
} from "./toastDefaults";

/**
 * What the rule about message length actually buys the reader, timed on the
 * sonner instance the application renders — the real component, with the real
 * `duration` handling — rather than on a stand-in that would agree with
 * whatever the wrapper passed it.
 *
 * Timers are faked so the lifetime is measured rather than waited out. A
 * warning that dies at four seconds proves nothing on its own: the number
 * this file pins is the one the wrapper computed, to within a second.
 */

/**
 * The warning the item form raises when the chosen category hides a handful
 * of fields — 194 characters, the shape measured dying at 4003 ms.
 */
const LONG_WARNING =
  "Ta kategoria ukrywa pola: data przydatności, partia, numer seryjny, " +
  "producent, cena zakupu, waga netto, data zakupu, lokalizacja, kod " +
  "kreskowy, kategoria — wpisane wartości nie zostaną zapisane.";

/** A warning with nothing to read: the floor is what keeps it visible. */
const SHORT_WARNING = "Nazwa jest wymagana";

function toasts(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>("[data-sonner-toast]"),
  );
}

/**
 * Raise a toast and let sonner's deferred state flush run — it batches the
 * addition through a zero-delay timer of its own, so a toast raised and
 * asserted in the same tick is not on screen yet.
 */
async function raise(show: () => void) {
  await act(async () => {
    show();
    vi.advanceTimersByTime(1);
  });
}

function letTimePass(ms: number) {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
}

describe("how long a message lives, measured on the rendered Toaster", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    installToastDefaults();
    render(
      <Toaster
        position="top-right"
        closeButton
        duration={SUCCESS_TOAST_DURATION_MS}
      />,
    );
  });

  afterEach(() => {
    act(() => {
      toast.dismiss();
    });
    letTimePass(500);
    cleanup();
    vi.useRealTimers();
  });

  it("keeps a long warning past the four seconds a success gets, and lets it go when its own time is up", async () => {
    await raise(() => {
      toast.warning(LONG_WARNING);
      toast.success("Zapisano");
    });
    expect(toasts()).toHaveLength(2);

    // The success is gone where it always goes — the warning, which the
    // reader has not finished, is still there beside it.
    letTimePass(SUCCESS_TOAST_DURATION_MS + 1000);
    expect(screen.getByText(LONG_WARNING)).toBeInTheDocument();
    expect(screen.queryByText("Zapisano")).not.toBeInTheDocument();

    const lifetime = readingToastDuration(LONG_WARNING);

    // A second before its reading time runs out …
    letTimePass(lifetime - SUCCESS_TOAST_DURATION_MS - 1000);
    expect(screen.getByText(LONG_WARNING)).toBeInTheDocument();

    // … and past it, gone again — a warning waits for a reader, it does not
    // own the screen. Sonner needs 200 ms to unmount what it has closed.
    letTimePass(2000);
    expect(screen.queryByText(LONG_WARNING)).not.toBeInTheDocument();
  });

  it("gives a short warning a floor rather than the four seconds a success gets", async () => {
    await raise(() => toast.warning(SHORT_WARNING));

    letTimePass(SUCCESS_TOAST_DURATION_MS + 500);
    expect(screen.getByText(SHORT_WARNING)).toBeInTheDocument();

    // The floor is 6000 ms: a warning that needs one glance still arrives
    // while the reader is mid-form, and four seconds was measured too short
    // for the same reason it was for an error.
    letTimePass(2000);
    expect(screen.queryByText(SHORT_WARNING)).not.toBeInTheDocument();
  });
});
