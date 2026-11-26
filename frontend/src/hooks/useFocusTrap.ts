import { useEffect, useRef } from "react";

import {
  getSheetFocusReturn,
  getTopmostOverlaySheetPanel,
} from "@/components/ui/overlayStack";

const FOCUSABLE_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * The last move of the focus: the element that lost it and the one that took
 * it. A field inside a sheet that focuses itself as it mounts has taken the
 * focus before the trap's effect runs, so `document.activeElement` is already
 * that field; the element that held the focus before is the one it came from.
 */
let lastFocusMove: { from: EventTarget | null; to: EventTarget | null } | null =
  null;
if (typeof document !== "undefined") {
  document.addEventListener(
    "focusout",
    (e) => {
      lastFocusMove = { from: e.target, to: e.relatedTarget };
    },
    true,
  );
}

/**
 * Traps keyboard focus within a modal container.
 * Returns a ref to attach to the container element.
 */
export function useFocusTrap<T extends HTMLElement = HTMLDivElement>(
  isActive: boolean,
) {
  const containerRef = useRef<T>(null);
  const previousFocusRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!isActive) return;

    const container = containerRef.current;
    if (!container) return;

    // The element to give the focus back to: what held it when this layer
    // opened. A field inside that took the focus as it mounted has already
    // moved it, so the move that brought it in names the opener.
    const active = document.activeElement;
    previousFocusRef.current =
      active && container.contains(active)
        ? lastFocusMove?.to === active &&
          lastFocusMove.from instanceof Element &&
          !container.contains(lastFocusMove.from)
          ? lastFocusMove.from
          : null
        : active;

    // A control inside that took the focus as it mounted — an `autoFocus`
    // field, or one focused by its own effect, which runs before this one —
    // keeps it. The first focusable element, usually the header's Close, is
    // only where focus goes when nothing inside asked for it.
    if (!container.contains(document.activeElement)) {
      container.querySelector<HTMLElement>(FOCUSABLE_SELECTORS)?.focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;

      const focusable = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS),
      );
      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      const previous = previousFocusRef.current;
      if (
        previous instanceof HTMLElement &&
        previous !== document.body &&
        previous.isConnected
      ) {
        previous.focus();
        return;
      }
      const opener = getSheetFocusReturn(container);
      if (opener) {
        opener.focus();
        return;
      }
      // Whatever had the focus when this layer opened is gone (a list the
      // reader picked in, a step that re-rendered) or was never a control.
      // Focus left on a removed element falls to <body>, outside a sheet that
      // is still open, and the next Tab leaves it. The sheet that stays open
      // takes it instead.
      const panel = getTopmostOverlaySheetPanel();
      if (panel && panel !== container) panel.focus();
    };
  }, [isActive]);

  return containerRef;
}
