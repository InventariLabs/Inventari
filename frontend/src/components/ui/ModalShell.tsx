/**
 * ModalShell — shared overlay/backdrop wrapper for fullscreen modals
 * that manage their own focus trap and inner content layout.
 *
 * Centralises the duplicated `fixed inset-0 z-[var(--z-modal)] ... bg-black/60`
 * wrappers that were being copy-pasted across ItemEditModal's not-found
 * state and main edit panel (and a few other fullscreen modals).
 *
 * Children render inside the overlay; the overlay itself handles the
 * click-outside-to-close behaviour when an onClose handler is provided.
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import { Z_TIER_TO_VAR, type SheetZTier } from "./Sheet";

type Backdrop = 50 | 60 | 80;

interface ModalShellProps {
  open: boolean;
  onClose?: () => void;
  children: React.ReactNode;
  className?: string;
  /** Wrapper z-index tier (see UI_GUIDELINES §4.1). Default "modal". */
  zIndex?: SheetZTier;
  /** Backdrop opacity. Default 60. */
  backdropOpacity?: Backdrop;
  /**
   * "bottom-sheet" (default): bottom-aligned on mobile with no padding,
   * centered with padding on sm+.
   * "centered": always centered with padding.
   * "fullscreen": fills the viewport (no padding, no centering).
   */
  layout?: "bottom-sheet" | "centered" | "fullscreen";
}

const backdropClass: Record<Backdrop, string> = {
  50: "bg-black/50",
  60: "bg-black/60",
  80: "bg-black/80",
};

export function ModalShell({
  open,
  onClose,
  children,
  className,
  zIndex = "modal",
  backdropOpacity = 60,
  layout = "bottom-sheet",
}: ModalShellProps) {
  // A press that starts on the content and ends on the backdrop
  // (because the content shrank under the cursor) delivers its `click` to the
  // backdrop. Only a press that *started* on the backdrop may close the modal.
  const pressStartedOnBackdrop = React.useRef(false);

  const handleMouseDown = React.useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      pressStartedOnBackdrop.current = e.target === e.currentTarget;
    },
    [],
  );

  const handleClick = React.useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const startedOnBackdrop = pressStartedOnBackdrop.current;
      pressStartedOnBackdrop.current = false;
      if (startedOnBackdrop && e.target === e.currentTarget) onClose?.();
    },
    [onClose],
  );

  if (!open) return null;
  const layoutClass =
    layout === "bottom-sheet"
      ? "items-end p-0 overflow-hidden sm:items-center sm:p-4"
      : layout === "centered"
        ? "items-center p-4"
        : "items-stretch p-0";

  return (
    <div
      className={cn(
        // `!m-0`: a page container's `space-y-*` would otherwise give this overlay
        // a top margin and leave the top of the app bar undimmed (see Sheet).
        "fixed inset-0 !m-0 z-[var(--z-modal)] flex justify-center animate-in fade-in duration-200",
        backdropClass[backdropOpacity],
        layoutClass,
        className,
      )}
      style={{ zIndex: Z_TIER_TO_VAR[zIndex] }}
      onMouseDown={onClose ? handleMouseDown : undefined}
      onClick={onClose ? handleClick : undefined}
    >
      <div onClick={(e) => e.stopPropagation()} className="contents">
        {children}
      </div>
    </div>
  );
}

export type { ModalShellProps };
export type { SheetZTier as ModalShellZTier, Backdrop as ModalShellBackdrop };
