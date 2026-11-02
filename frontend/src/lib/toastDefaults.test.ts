import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import {
  SUCCESS_TOAST_DURATION_MS,
  UNDO_TOAST_DURATION_MS,
  readingToastDuration,
  installToastDefaults,
} from "./toastDefaults";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

/** The refusal measured on a 390px screen — 181 characters, six lines. */
const LONG_REFUSAL =
  "Nie można zakończyć ani anulować tego dokumentu, dopóki trwa 1 aktywna " +
  "sesja kompletacji. Najpierw je zakończ lub anuluj (identyfikator sesji: " +
  "d74c3546-0000-0000-0000-000000000000)";

/**
 * The warning the item form raises when the chosen category hides a handful
 * of fields — 194 characters, the shape measured dying at 4003 ms.
 */
const LONG_WARNING =
  "Ta kategoria ukrywa pola: data przydatności, partia, numer seryjny, " +
  "producent, cena zakupu, waga netto, data zakupu, lokalizacja, kod " +
  "kreskowy, kategoria — wpisane wartości nie zostaną zapisane.";

describe("readingToastDuration", () => {
  it("gives a long refusal longer than a success gets", () => {
    expect(LONG_REFUSAL.length).toBeGreaterThan(150);
    expect(readingToastDuration(LONG_REFUSAL)).toBeGreaterThan(
      SUCCESS_TOAST_DURATION_MS,
    );
  });

  // The reader has to see it, find the sentence, and reach the close button.
  it("leaves a long refusal on screen well past the four seconds it used to get", () => {
    expect(readingToastDuration(LONG_REFUSAL)).toBeGreaterThanOrEqual(10000);
  });

  it("gives a short refusal a floor rather than a glance", () => {
    expect(readingToastDuration("Nie udało się")).toBeGreaterThanOrEqual(6000);
  });

  it("does not let a pathological message own the screen", () => {
    expect(readingToastDuration("x".repeat(5000))).toBeLessThanOrEqual(20000);
  });

  it("survives a message that is not a string", () => {
    expect(readingToastDuration(undefined)).toBeGreaterThanOrEqual(6000);
  });
});

describe("installToastDefaults", () => {
  // Captured before the install: from then on ``toast.error`` and
  // ``toast.warning`` are the wrappers, and what a wrapper passes on is what
  // these tests are about.
  const raisedError = vi.mocked(toast.error);
  const raisedWarning = vi.mocked(toast.warning);
  const raisedSuccess = vi.mocked(toast.success);

  beforeEach(() => {
    raisedError.mockClear();
    raisedWarning.mockClear();
    raisedSuccess.mockClear();
  });

  it("hands every error toast a duration, without any call site asking", () => {
    installToastDefaults();

    toast.error(LONG_REFUSAL);

    expect(raisedError).toHaveBeenCalledWith(
      LONG_REFUSAL,
      expect.objectContaining({ duration: readingToastDuration(LONG_REFUSAL) }),
    );
  });

  it("hands every warning a duration too — a warning asks to be read as well", () => {
    installToastDefaults();

    toast.warning(LONG_WARNING);

    expect(raisedWarning).toHaveBeenCalledWith(
      LONG_WARNING,
      expect.objectContaining({ duration: readingToastDuration(LONG_WARNING) }),
    );
  });

  it("leaves a caller that named its own duration alone", () => {
    installToastDefaults();

    toast.error("Krótko", { duration: 1000 });

    expect(raisedError).toHaveBeenCalledWith(
      "Krótko",
      expect.objectContaining({ duration: 1000 }),
    );
  });

  // Passes before and after the rule, deliberately: it pins the half of the
  // behaviour the rule must not change, in the branch the rule now wraps.
  it("leaves a warning whose caller named a duration alone", () => {
    installToastDefaults();

    toast.warning("Krótko", { duration: 1000 });

    expect(raisedWarning).toHaveBeenCalledWith(
      "Krótko",
      expect.objectContaining({ duration: 1000 }),
    );
  });

  // A toast that offers a way back is not an acknowledgement: the button has
  // to be reachable, and a phone cannot pause the countdown to reach it.
  it("keeps a success that carries an undo action on screen longer than a plain success", () => {
    installToastDefaults();
    const action = { label: "Undo", onClick: vi.fn() };

    toast.success("Group removed.", { action });

    expect(UNDO_TOAST_DURATION_MS).toBeGreaterThan(SUCCESS_TOAST_DURATION_MS);
    expect(raisedSuccess).toHaveBeenCalledWith(
      "Group removed.",
      expect.objectContaining({ action, duration: UNDO_TOAST_DURATION_MS }),
    );
  });

  it("leaves a plain success to the Toaster's own four seconds", () => {
    installToastDefaults();

    toast.success("Saved.");

    expect(raisedSuccess).toHaveBeenCalledWith("Saved.", undefined);
  });

  it("leaves a success with an action whose caller named a duration alone", () => {
    installToastDefaults();

    toast.success("Done.", {
      action: { label: "Undo", onClick: vi.fn() },
      duration: 1000,
    });

    expect(raisedSuccess).toHaveBeenCalledWith(
      "Done.",
      expect.objectContaining({ duration: 1000 }),
    );
  });
});
