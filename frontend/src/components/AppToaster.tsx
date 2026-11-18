import { useTranslation } from "react-i18next";
import { Toaster } from "sonner";
import { SUCCESS_TOAST_DURATION_MS } from "@/lib/toastDefaults";

/**
 * The notification surface — the one place toasts are configured, and the one
 * place a test can read that configuration back.
 *
 * The props live here, where a test can read them back, rather than inline in
 * `main.tsx`. Deleting either the button or the `installToastDefaults()` call
 * breaks a test, so a 20px close button cannot reach a touch screen unnoticed.
 *
 * `closeButton`: sonner pauses its countdown on hover and on focus, and a
 * phone has neither — without an explicit close there is no way to hold a
 * message still, or to be rid of one early.
 *
 * Both names come from the catalogue. Sonner's own defaults are English
 * ("Close toast", "Notifications alt+T") and a screen reader announces them
 * in a Polish interface.
 *
 * The close button's name travels in `toastOptions`, not as the prop of the
 * same name beside it: sonner 2.0.7 declares `closeButtonAriaLabel` on
 * `<Toaster>` and then forwards it to each toast from `toastOptions` alone,
 * so the top-level prop leaves the button announcing "Close toast".
 */
export default function AppToaster() {
  const { t } = useTranslation("common");

  return (
    <Toaster
      position="top-right"
      style={{ top: 72 }}
      closeButton
      toastOptions={{ closeButtonAriaLabel: t("a11y.closeToast") }}
      containerAriaLabel={t("a11y.toastsRegion")}
      duration={SUCCESS_TOAST_DURATION_MS}
    />
  );
}
