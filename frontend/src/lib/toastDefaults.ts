import { toast } from "sonner";

/**
 * How long a message stays on screen, by what it costs the reader to lose it.
 *
 * Sonner's default is four seconds for everything, and it pauses the countdown
 * on hover and on focus — neither of which a phone has. Measured on a 390px
 * screen: a refusal of 181 characters ("… you cannot finish this document
 * while a picking session is open … session id d74c3546-…") filled six lines
 * and was gone 4352 ms after the click. The document stayed CONFIRMED for no
 * visible reason, and the first reading of the app was "409 with no message" —
 * which was false. The message was there. It had time to disappear.
 *
 * This is not one message: the error catalogue holds 67 sentences longer than
 * 90 characters, the longest 271. They are written well — cause and way out —
 * and that is exactly why they need to be read.
 *
 * Errors and warnings are the same class here, because they ask the same
 * thing of the reader. The warning was left out of the first version of this
 * rule, and measured on the same instance: 193 characters, gone at 4003 ms,
 * beside a 180-character error that got 12 601 ms. The equipment bulk actions
 * raise exactly that shape of warning — "12 succeeded, 3 failed" with the
 * rows that failed named underneath — so four seconds was cutting off the
 * half of the message that says what to do next.
 */
export const SUCCESS_TOAST_DURATION_MS = 4000;

/**
 * A success that carries an undo action is not an acknowledgement: the reader
 * has to notice it, decide and reach the button, and a phone cannot pause the
 * countdown the way a pointer can.
 */
export const UNDO_TOAST_DURATION_MS = 10000;

/** Below this, a message that asks for something is a glance; the floor is what makes it a read. */
const READING_TOAST_MINIMUM_MS = 6000;

/** Roughly 14 characters a second — a stressed reader, not a speed reader. */
const MS_PER_CHARACTER = 70;

/** Past this a toast has stopped being a toast; the close button takes over. */
const READING_TOAST_MAXIMUM_MS = 20000;

export function readingToastDuration(message: unknown): number {
  const length = typeof message === "string" ? message.length : 0;
  return Math.min(
    READING_TOAST_MAXIMUM_MS,
    Math.max(READING_TOAST_MINIMUM_MS, length * MS_PER_CHARACTER),
  );
}

let installed = false;

/**
 * Give every message that asks to be read a duration matched to its length,
 * once, centrally.
 *
 * Sonner takes a duration per toast and a default per `<Toaster>`, and has no
 * per-type default in between — which is the shape this rule needs, since it
 * is about the class of message and not about any call site. The alternative
 * was passing a duration at 291 `toast.error` calls and 11 `toast.warning`
 * ones, and a rule spread over 300 places is a rule nobody can change
 * afterwards.
 *
 * `success` is left alone — it is an acknowledgement, and four seconds is
 * what one needs — unless it carries an action: a way back needs time to be
 * used, so it gets `UNDO_TOAST_DURATION_MS`. `loading` owns the screen until
 * it is replaced.
 *
 * A caller that names its own duration keeps it: the defaults are underneath
 * `data`, not on top of it.
 */
export function installToastDefaults(): void {
  if (installed) return;
  installed = true;

  for (const type of ["error", "warning"] as const) {
    const raise = toast[type];
    toast[type] = ((message, data) =>
      raise(message, {
        duration: readingToastDuration(message),
        ...data,
      })) as typeof toast.error;
  }

  const acknowledge = toast.success;
  toast.success = ((message, data) =>
    acknowledge(
      message,
      data?.action ? { duration: UNDO_TOAST_DURATION_MS, ...data } : data,
    )) as typeof toast.success;
}
