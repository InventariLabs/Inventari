import { useEffect, useRef } from "react";

import { getTopmostOverlaySheetPanel } from "@/components/ui/overlayStack";

const FOCUSABLE_SELECTORS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

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

    previousFocusRef.current = document.activeElement;

    const container = containerRef.current;
    if (!container) return;

    const focusableElements =
      container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTORS);
    if (focusableElements.length > 0) {
      focusableElements[0].focus();
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
