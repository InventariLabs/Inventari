import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ScannerReadyHint } from "@/components/ui/ScannerReadyHint";
import de from "@/i18n/locales/de/common.json";
import en from "@/i18n/locales/en/common.json";
import es from "@/i18n/locales/es/common.json";
import fr from "@/i18n/locales/fr/common.json";
import pl from "@/i18n/locales/pl/common.json";

// A browser cannot see a keyboard-wedge scanner, so the hint may only say that
// one can be used here — on a phone with no scanner it must not read as a
// detected device.
describe("ScannerReadyHint", () => {
  it("says a scanner can be used, not that one is present", () => {
    render(<ScannerReadyHint />);
    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();
  });

  it.each([
    ["en", en],
    ["pl", pl],
    ["de", de],
    ["fr", fr],
    ["es", es],
  ])("has no 'ready' wording in %s", (_lang, bundle) => {
    const b = bundle as Record<string, unknown>;
    expect(b).not.toHaveProperty("scannerReady");
    expect(typeof b.scannerHint).toBe("string");
  });
});
