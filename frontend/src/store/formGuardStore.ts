import { create } from "zustand";

/**
 * Which form is holding unsaved work, by its reader-facing name.
 *
 * One slot, not a registry: the app shows one page at a time, so at most one
 * form can be holding work. The navigation gate reads this before it lets a
 * link through: the equipment form used to lose eight filled fields to a
 * click on the module tab, with no question asked and no way back.
 *
 * The label travels already localized — the store is not a translator.
 *
 * Why registration is opt-in — the recorded decision: knowing whether a form
 * is dirty is the form's own knowledge, and there is no shared draft state a
 * gate could read. What registers is the surface where a stray click costs
 * real work — a dozen fields typed by hand into the page: the equipment add
 * form, the product add form, the approval path form, and a stock take
 * mid-count, rows of numbers no single save button commits. Forms the app
 * rebuilds cheaply (an import dialog, a filter panel) deliberately stay out
 * — asking there would teach the reader to click through the question.
 * A dialog is no reason to stay out: its tabs and links are out of reach,
 * but the command palette opens over it and navigates through the gate, so
 * a long form in a dialog is asked like any other.
 *
 * A new long-lived form registers with one line, `useFormGuard(isDirty,
 * label)`. The survey in `src/test/form-guard-coverage.test.ts` is what
 * keeps the class from eroding: a multi-field form that neither registers
 * nor carries a reason there fails.
 */
interface FormGuardState {
  dirtyForm: string | null;
  setDirtyForm: (label: string | null) => void;
}

export const useFormGuardStore = create<FormGuardState>((set) => ({
  dirtyForm: null,
  setDirtyForm: (label) => set({ dirtyForm: label }),
}));
