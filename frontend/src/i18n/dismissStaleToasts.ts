import { toast } from "sonner";
import i18n from "./config";

/**
 * Clears visible notifications when the interface language changes.
 *
 * A toast is a string, composed once and handed to sonner — there is nothing
 * left to re-render in the new language, and no key to look up again. So a
 * message raised before the switch sits on top of a screen that has already
 * changed language, which is how the first screen after signing in came to
 * show two.
 *
 * Dismissing is the honest option of the two available: a notification that
 * has gone is a notification the reader may have missed, but one left in the
 * language they just moved away from is one they may not be able to read at
 * all.
 */
export function dismissToastsOnLanguageChange(): () => void {
  const clear = () => toast.dismiss();
  i18n.on("languageChanged", clear);
  return () => i18n.off("languageChanged", clear);
}
