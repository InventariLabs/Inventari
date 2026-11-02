import { toast } from "sonner";

/**
 * Whether the clipboard took the text, and when it did not, why.
 *
 * Outside a secure context — the usual self-hosted install, reached over
 * `http://` on an address in the local network — `navigator.clipboard` does
 * not exist at all, and awaiting it throws. Inside one the call can still
 * refuse: the permission is denied, or the document has lost focus. A button
 * that awaits it with no path for either never changes state, and the reader
 * is left in front of a silent control over a value they may only be shown
 * once.
 */
export type CopyOutcome = "copied" | "no-clipboard" | "error";

/**
 * One place that asks the clipboard for a text, so every copy button in the
 * application answers the same way when there is nothing to answer with.
 */
export async function copyText(text: string): Promise<CopyOutcome> {
  if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
    return "no-clipboard";
  }
  try {
    await navigator.clipboard.writeText(text);
    return "copied";
  } catch {
    return "error";
  }
}

/**
 * The path a copy button with nothing else to say takes: copy, and when the
 * clipboard is not there or refuses the text, say what to do instead.
 *
 * `message` is already translated — one sentence lives in the `common`
 * bundle and every module that owns a copy button borrows it, rather than
 * each keeping a wording of its own that drifts. Returns whether the text
 * landed, so the caller's success notice stays its own.
 */
export async function copyTextOrExplain(
  text: string,
  message: string,
): Promise<boolean> {
  const outcome = await copyText(text);
  if (outcome !== "copied") {
    toast.error(message);
    return false;
  }
  return true;
}
