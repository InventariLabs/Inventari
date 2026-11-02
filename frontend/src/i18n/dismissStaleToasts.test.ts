import { describe, it, expect, vi, afterEach } from "vitest";
import { toast } from "sonner";
import i18n from "./config";
import { dismissToastsOnLanguageChange } from "./dismissStaleToasts";

vi.mock("sonner", () => ({
  toast: { dismiss: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

/**
 * The first screen after signing in showed two languages at once: the shell in
 * the account's, and a "signed in" toast still in the one the visitor had been
 * browsing in. A toast is a composed string — nothing re-renders it — so the
 * switch has to take it away.
 */
describe("visible notifications and a language change", () => {
  const unsubscribers: Array<() => void> = [];

  afterEach(() => {
    while (unsubscribers.length) unsubscribers.pop()!();
    vi.mocked(toast.dismiss).mockClear();
  });

  it("clears them when the language changes", async () => {
    unsubscribers.push(dismissToastsOnLanguageChange());

    await i18n.changeLanguage("de");

    expect(toast.dismiss).toHaveBeenCalled();
  });

  it("stops clearing once the subscription is dropped", async () => {
    const stop = dismissToastsOnLanguageChange();
    stop();

    await i18n.changeLanguage("fr");

    expect(toast.dismiss).not.toHaveBeenCalled();
  });
});
