import { useEffect, useRef } from "react";
import { flushSync } from "react-dom";
import { scannedCode } from "@/lib/scan/scannedCode";

/**
 * Mark a field as one a hardware scanner may type into: the hook then takes a
 * scan there as well, instead of leaving it to the field.
 */
export const SCANNER_INPUT_ATTRIBUTE = "data-scanner-input";

/**
 * Mark a field that holds nothing but the code being entered — a barcode
 * field, not a search box. When a burst closes there, the hook hands over
 * everything the field holds, because a code typed with one pause in it comes
 * as a burst of only its end. Without the mark the burst alone is the code:
 * whatever else the field holds is the person's own text.
 */
export const SCANNER_WHOLE_ATTRIBUTE = "data-scanner-whole";

/**
 * Mark a field that holds a number the person types — a quantity — yet may
 * have the scanner's keys land in it because it has the focus. The hook takes
 * the scan there too and then puts the field back as it was before the burst,
 * so what the person typed first is still in it.
 */
export const SCANNER_KEEP_ATTRIBUTE = "data-scanner-keep";

/** A scanner sends a key every few ms; a person, rarely faster than this. */
const MAX_KEY_GAP_MS = 50;
/**
 * A burst this long at a person's fastest is a scan. A shorter one — a zone's
 * shelf code such as "A" — is one only at a scanner's own pace, every key
 * under `SHORT_CODE_KEY_GAP_MS`: a digit and Enter typed into a quantity are
 * a person's even when they come quickly.
 */
const MIN_CODE_LENGTH = 4;
const SHORT_CODE_KEY_GAP_MS = 30;
const TERMINATORS = new Set(["Enter", "Tab"]);
/** A scanner's double read: the same code again within this window. */
const REPEAT_WINDOW_MS = 300;

interface Options {
  /** Listen only while true — e.g. while a session is open. */
  enabled?: boolean;
}

function isEditable(target: EventTarget | null): target is HTMLElement {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    target.isContentEditable
  );
}

function optedIn(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.hasAttribute(SCANNER_INPUT_ATTRIBUTE) || keepsValue(target))
  );
}

function keepsValue(target: EventTarget | null): target is HTMLInputElement {
  return (
    target instanceof HTMLInputElement &&
    target.hasAttribute(SCANNER_KEEP_ATTRIBUTE)
  );
}

/**
 * The code a burst closes. In a field marked `SCANNER_WHOLE_ATTRIBUTE` the
 * field holds the whole of it when a person typed its start slowly and only
 * the end came under the key gap: the burst alone would be a cut code.
 */
function wholeCode(target: EventTarget | null, burst: string): string {
  if (!(target instanceof HTMLInputElement)) return burst;
  if (!target.hasAttribute(SCANNER_WHOLE_ATTRIBUTE)) return burst;
  const held = target.value;
  return held.length > burst.length && held.endsWith(burst) ? held : burst;
}

/** Put `value` back the way a person's edit would: React hears it too. */
function restoreValue(field: HTMLInputElement, value: string) {
  if (field.value === value) return;
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(field, value);
  // Sync, so a handler that reads the field's state next sees it restored.
  flushSync(() => {
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/**
 * Hear a keyboard-wedge barcode scanner on the whole page.
 *
 * A USB or Bluetooth scanner presents itself as a keyboard: a code arrives as
 * a burst of keys a few ms apart, closed by Enter (or Tab). A burst of at
 * least four characters, each under 50 ms after the previous one, is a scan,
 * and so is a shorter one whose every key came under 30 ms:
 * `onScan` gets the code once and the terminator is swallowed, so no form
 * submits and no button under the focus fires. Keys typed into an editable
 * field are the field's, unless it carries `SCANNER_INPUT_ATTRIBUTE`; there
 * the hook also takes the path Android scanning keyboards use, which insert
 * the whole code as one text insertion and then press Enter (one character,
 * when the code is one letter). A field with
 * `SCANNER_KEEP_ATTRIBUTE` is taken the same way and then given back the value
 * it held before the scan. The same code
 * read again within 300 ms is a double read: its terminator is swallowed and
 * the code is not emitted a second time.
 */
export function useScannerInput(
  onScan: (code: string) => void,
  { enabled = true }: Options = {},
) {
  // The latest handler, without re-subscribing on every render.
  const onScanRef = useRef(onScan);
  onScanRef.current = onScan;

  useEffect(() => {
    if (!enabled) return;
    let buffer = "";
    let lastAt = 0;
    // The longest pause between two keys of the burst so far.
    let slowestGap = 0;
    // The last key named none: what is inserted next is the IME's text.
    let imeKey = false;
    let lastCode = "";
    let lastEmittedAt = 0;
    // What a keep field held before the burst began.
    let valueBefore: string | null = null;
    let lastTarget: EventTarget | null = null;

    const reset = () => {
      buffer = "";
      lastAt = 0;
      slowestGap = 0;
      valueBefore = null;
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (isEditable(target) && !optedIn(target)) {
        reset();
        return;
      }
      // A burst is one run of keys to one field: keys a person typed into
      // the quantity are not the start of the code that follows in another.
      if (target !== lastTarget) reset();
      lastTarget = target;
      const now = Date.now();
      const fresh = lastAt !== 0 && now - lastAt < MAX_KEY_GAP_MS;
      imeKey = event.key === "Unidentified";

      if (TERMINATORS.has(event.key)) {
        const scannerPace =
          Math.max(slowestGap, now - lastAt) < SHORT_CODE_KEY_GAP_MS;
        if (
          fresh &&
          buffer.length > 0 &&
          (buffer.length >= MIN_CODE_LENGTH || scannerPace)
        ) {
          event.preventDefault();
          event.stopPropagation();
          const code = wholeCode(target, buffer);
          if (keepsValue(target) && valueBefore !== null) {
            restoreValue(target, valueBefore);
          }
          reset();
          if (code === lastCode && now - lastEmittedAt < REPEAT_WINDOW_MS) {
            return;
          }
          lastCode = code;
          lastEmittedAt = now;
          // A QR's whole address is the code it carries.
          onScanRef.current(scannedCode(code));
          return;
        }
        reset();
        return;
      }
      if (
        event.key.length !== 1 ||
        event.ctrlKey ||
        event.metaKey ||
        event.altKey
      ) {
        // An IME keydown ("Unidentified", keyCode 229) belongs to the
        // insertion that follows it, and a scanner presses Shift for every
        // capital it sends; any other key ends a burst.
        if (event.key !== "Unidentified" && event.key !== "Shift") reset();
        return;
      }
      if (!fresh) valueBefore = keepsValue(target) ? target.value : null;
      slowestGap = fresh ? Math.max(slowestGap, now - lastAt) : 0;
      buffer = fresh ? buffer + event.key : event.key;
      lastAt = now;
    };

    const handleBeforeInput = (event: Event) => {
      if (!optedIn(event.target)) return;
      const { data, inputType } = event as InputEvent;
      if (
        (inputType === "insertText" || inputType === "insertReplacementText") &&
        data &&
        // A key typed here was taken on its keydown; a single character is
        // an insertion of its own only after an IME keydown.
        (data.length > 1 || imeKey)
      ) {
        buffer = data;
        lastAt = Date.now();
        slowestGap = 0;
        // The terminator that follows belongs to this field's scan.
        lastTarget = event.target;
        const field = event.target;
        valueBefore = keepsValue(field) ? field.value : null;
      }
    };

    // Capture, so the scan is taken before the field or the form sees the
    // terminator.
    document.addEventListener("keydown", handleKeyDown, true);
    document.addEventListener("beforeinput", handleBeforeInput, true);
    return () => {
      document.removeEventListener("keydown", handleKeyDown, true);
      document.removeEventListener("beforeinput", handleBeforeInput, true);
    };
  }, [enabled]);
}
