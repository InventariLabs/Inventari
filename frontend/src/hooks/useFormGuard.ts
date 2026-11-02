import { useEffect } from "react";
import { useFormGuardStore } from "@/store/formGuardStore";

/**
 * Report this form to the navigation gate while it holds unsaved work.
 *
 * The three lines this replaces — read `setDirtyForm`, set it to the label
 * while dirty, clear it on unmount — were copied verbatim into every
 * consumer, and the store's own docstring told the next author to copy them
 * again. With a fourth consumer that stopped being a pattern and became a
 * hook: the cleanup is the part that is easy to leave out, and a form that
 * forgets it leaves the whole app asking about work the reader already saved.
 *
 * The same flag also guards the page itself: a reload, a phone's
 * pull-to-refresh or a closed tab ask the browser's own question, which the
 * in-app exits cannot reach.
 *
 * `label` travels already localized — the gate says it back to the reader,
 * and the store is not a translator.
 */
export function useFormGuard(isDirty: boolean, label: string): void {
  const setDirtyForm = useFormGuardStore((s) => s.setDirtyForm);
  useEffect(() => {
    setDirtyForm(isDirty ? label : null);
    return () => setDirtyForm(null);
  }, [isDirty, label, setDirtyForm]);

  useEffect(() => {
    if (!isDirty) return;
    const askBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Older engines show the prompt only when a value is set.
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", askBeforeUnload);
    return () => window.removeEventListener("beforeunload", askBeforeUnload);
  }, [isDirty]);
}
