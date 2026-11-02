import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useFocusTrap } from "@/hooks/useFocusTrap";
import { Button } from "@/components/ui/Button";
import {
  hasAlertDialogOpen,
  hasListboxOpen,
  hasPopperLayerOpen,
  registerOverlaySheet,
} from "./overlayStack";

/**
 * Z-index tiers per UI_GUIDELINES §4.1 (: no numeric literals — the
 * layer system is the single source of truth).
 */
export type SheetZTier = "modal" | "modal-nested" | "confirm" | "fullscreen";

export const Z_TIER_TO_VAR: Record<SheetZTier, string> = {
  modal: "var(--z-modal)",
  "modal-nested": "var(--z-modal-nested)",
  confirm: "var(--z-confirm)",
  fullscreen: "var(--z-fullscreen)",
};

interface SheetProps {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl" | "4xl" | "5xl" | "6xl";
  /**
   * z-index tier (per UI_GUIDELINES §4.1).
   * "modal" default; "modal-nested" for nested modals, "confirm" for
   * confirm dialogs, "fullscreen" for fullscreen wizards.
   */
  zIndex?: SheetZTier;
  /**
   * Backdrop opacity (50 default, 60 for sheets with busy backgrounds,
   * 80 for image/scan viewers).
   */
  backdropOpacity?: 50 | 60 | 80;
  /**
   * Accessible name for the dialog (sets aria-label on the content panel).
   * Use this when the modal has no visible heading, or when the heading
   * text would be too long/noisy to announce.
   * If the modal has a visible heading inside children, prefer
   * `aria-labelledby` and point it at that heading's id.
   */
  "aria-label"?: string;
  /**
   * Id of the visible heading that names this dialog. The better of the two
   * when there is one: a screen reader then announces the same words the
   * screen shows, and the two cannot drift apart.
   */
  "aria-labelledby"?: string;
  /**
   * Accessible description for the dialog (sets aria-describedby on the
   * content panel).
   */
  "aria-describedby"?: string;
  /**
   * Id of the panel, for a control that names it with `aria-controls` — the
   * trigger of a picker that opens as a sheet below `sm:`.
   */
  id?: string;
  /** Whether clicking the backdrop closes the sheet (default true) */
  closeOnBackdropClick?: boolean;
  /**
   * Full-bleed working surface on mobile (no backdrop, no rounding, full
   * height), standard centered modal from `sm` up.
   *
   * For operator-facing flows — picking, receiving, scanning — where the
   * phone should show the task edge-to-edge rather than a bottom sheet.
   * Implies no backdrop-click-to-close: on mobile the "backdrop" *is* the
   * surface, so a click anywhere would dismiss the screen.
   */
  fullBleedOnMobile?: boolean;
  /**
   * Full-bleed at every width: the panel *is* the viewport, with no backdrop
   * to click and nothing to round.
   *
   * The shape the fullscreen layer is named for (UI_GUIDELINES §4.1) — a
   * wizard standing in front of the application rather than a card over it.
   * Supersedes `fullBleedOnMobile`, and ignores `maxWidth`: a panel that fills
   * the screen has no width of its own to cap.
   */
  fullBleed?: boolean;
  /**
   * A dialog holding something the user cannot get back — a one-time secret,
   * a generated key — must not close by accident (default true, i.e. it may).
   * Set to false and both accidental exits go away at once: Escape and the
   * backdrop click. Escape is still swallowed, so it does not travel down to
   * the layer underneath.
   */
  dismissible?: boolean;
}

const maxWidthClasses: Record<NonNullable<SheetProps["maxWidth"]>, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  "2xl": "max-w-2xl",
  "3xl": "max-w-3xl",
  "4xl": "max-w-4xl",
  "5xl": "max-w-5xl",
  "6xl": "max-w-6xl",
};

// Spelled out rather than built from a template — Tailwind only extracts
// class names it can see statically.
const maxWidthSmClasses: Record<NonNullable<SheetProps["maxWidth"]>, string> = {
  sm: "sm:max-w-sm",
  md: "sm:max-w-md",
  lg: "sm:max-w-lg",
  xl: "sm:max-w-xl",
  "2xl": "sm:max-w-2xl",
  "3xl": "sm:max-w-3xl",
  "4xl": "sm:max-w-4xl",
  "5xl": "sm:max-w-5xl",
  "6xl": "sm:max-w-6xl",
};

const backdropOpacityClasses: Record<
  NonNullable<SheetProps["backdropOpacity"]>,
  string
> = {
  50: "bg-black/50",
  60: "bg-black/60",
  80: "bg-black/80",
};

const backdropOpacitySmClasses: Record<
  NonNullable<SheetProps["backdropOpacity"]>,
  string
> = {
  50: "sm:bg-black/50",
  60: "sm:bg-black/60",
  80: "sm:bg-black/80",
};

/**
 * Bottom sheet on mobile, centered modal on desktop — or, with `fullBleed`,
 * the fullscreen layer's own surface at every width.
 * Follows UI_GUIDELINES.md Section 4.3.
 *
 * Provides:
 * - role="dialog" + aria-modal="true" on the content panel
 * - aria-label / aria-describedby on the content panel
 * - Focus trap (Tab cycling, focus save/restore)
 * - ESC closes the sheet when it is the highest one open
 * - Body scroll lock while open
 */
export function Sheet({
  open,
  onClose,
  children,
  className,
  maxWidth = "md",
  zIndex = "modal",
  backdropOpacity = 50,
  closeOnBackdropClick = true,
  fullBleedOnMobile = false,
  fullBleed = false,
  dismissible = true,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  "aria-describedby": ariaDescribedBy,
  id,
}: SheetProps) {
  const containerRef = useFocusTrap(open);
  // A press that starts inside the panel and ends on the backdrop
  // (because the content shrank under the cursor) delivers its `click` to the
  // backdrop. Only a press that *started* on the backdrop may close the sheet.
  const pressStartedOnBackdrop = useRef(false);

  const handleBackdropMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      pressStartedOnBackdrop.current = e.target === e.currentTarget;
    },
    [],
  );

  const handleBackdropClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const startedOnBackdrop = pressStartedOnBackdrop.current;
      pressStartedOnBackdrop.current = false;
      if (startedOnBackdrop && e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  // ESC + body scroll lock — overlay-specific, deliberately kept here
  // (useFocusTrap handles only Tab cycling + focus save/restore).
  useEffect(() => {
    if (!open) return;

    // Tells the dialog underneath — if there is one — that a layer is stacked
    // on top of it, so Escape closes this and not both. The panel travels
    // with the registration so focus has a place to fall back to when the
    // element a question came from is gone.
    const sheet = registerOverlaySheet(containerRef.current);

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // The highest sheet owns the press. A sheet standing under another —
      // the wizard under the list its first step opens — stands idle: acting
      // here closed it, or raised its discard question, over a list the
      // keystroke was aimed at.
      if (!sheet.isTopmost()) return;
      // A list opened from inside the sheet — units, an ingredient
      // suggestion, a date — owns this press. Radix closes it from its own
      // listener; closing the sheet as well threw away everything typed into
      // it, on a keystroke aimed at the list.
      if (hasPopperLayerOpen()) return;
      // The product picker is a list of its own, closed by its input's key
      // handler: the first Escape closes it, the next one the sheet.
      if (hasListboxOpen()) return;
      // A question raised over the sheet owns the press too — a discard guard.
      // Radix dismisses it from a listener of its own, in the same phase this
      // one runs in; a sheet that also acted on the press would close, or ask
      // the same question a second time, in the keystroke meant to answer it.
      if (hasAlertDialogOpen()) return;
      // Swallowed either way: an undismissable sheet that let Escape through
      // would close the form behind it instead of itself.
      e.preventDefault();
      if (dismissible) onClose();
    };
    // Capture, so this decision is taken before Radix reads `defaultPrevented`.
    // The press that closes an empty sheet may raise a second layer — "you
    // have typed something, discard it?" — and that layer mounts inside the
    // flush this handler triggers. Radix registers its own Escape listener
    // during that flush, while the key event is still travelling, and finds
    // the press prevented — so the question stands rather than being dismissed
    // by the keystroke that asked it.
    document.addEventListener("keydown", handleEscape, { capture: true });

    return () => {
      sheet.release();
      document.removeEventListener("keydown", handleEscape, {
        capture: true,
      });
      document.body.style.overflow = originalOverflow;
    };
  }, [open, onClose, dismissible, containerRef]);

  if (!open) return null;

  // A bleed surface is the screen: there is nothing outside the panel for a
  // press to land on, at either width, so no backdrop-click path is wired.
  const backdropCloses =
    closeOnBackdropClick && dismissible && !fullBleedOnMobile && !fullBleed;

  const overlay = (
    <div
      className={cn(
        // `!m-0`: rendered in place the overlay is a flow sibling of the page
        // around it, and a spaced container (`space-y-6`) hands it that
        // space as a top margin — 24px of the app bar left undimmed and
        // clickable behind the modal. It is not portaled, so the margin goes.
        "fixed inset-0 !m-0 justify-center animate-in fade-in duration-200",
        fullBleed
          ? "flex flex-col bg-surface-card"
          : fullBleedOnMobile
            ? [
                "flex flex-col bg-surface-card sm:items-center sm:justify-center sm:p-4",
                backdropOpacitySmClasses[backdropOpacity],
              ]
            : [
                "flex items-end sm:items-center p-0 sm:p-4",
                backdropOpacityClasses[backdropOpacity],
              ],
      )}
      style={{ zIndex: Z_TIER_TO_VAR[zIndex] }}
      onMouseDown={backdropCloses ? handleBackdropMouseDown : undefined}
      onClick={backdropCloses ? handleBackdropClick : undefined}
    >
      <div
        ref={containerRef}
        id={id}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        aria-describedby={ariaDescribedBy}
        className={cn(
          // The panel takes the focus when a question raised over the sheet
          // gives it back and the element it came from is gone; a ring around
          // a whole screen would say nothing.
          "w-full flex flex-col outline-none",
          fullBleed
            ? "h-full bg-surface-card overflow-hidden"
            : fullBleedOnMobile
              ? [
                  "sm:bg-surface-card sm:border sm:border-border sm:rounded-2xl sm:shadow-xl",
                  "h-full sm:h-auto sm:max-h-[90vh] overflow-hidden",
                  maxWidthSmClasses[maxWidth],
                ]
              : [
                  "bg-surface-card border border-border rounded-t-3xl sm:rounded-2xl shadow-xl",
                  maxWidthClasses[maxWidth],
                  "max-h-[90vh] overflow-hidden animate-in slide-in-from-bottom sm:zoom-in-95 duration-300",
                ],
          className,
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );

  // The full-bleed panel *is* the viewport. Rendered in place it is a flow
  // sibling of the page around it, and a spaced page container — `space-y-6`
  // on the storages screen — hands it that space as a top margin, so the
  // application showed through a 24px strip above a screen meant to cover it.
  // Nothing in the body can do that to a portal. A panel that bleeds on a
  // phone only is the viewport there in the same way — the receiving and
  // picking screens open from a document page laid out in such a column.
  return fullBleed || fullBleedOnMobile
    ? createPortal(overlay, document.body)
    : overlay;
}

/**
 * Heading for a `Sheet`. Plain `<h2>` — `Sheet` is hand-rolled, not Radix,
 * so there is no primitive to forward to (unlike `Dialog.Title`).
 */
export function SheetTitle({
  className,
  ...props
}: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 className={cn("text-lg font-semibold text-on", className)} {...props} />
  );
}

/**
 * Scroll layer for a `Sheet`. The panel itself is `overflow-hidden`,
 * so content longer than the panel needs a shrinkable, scrollable child —
 * `min-h-0` is what lets a flex child shrink below its content size, without
 * it `overflow-y-auto` never engages.
 *
 * Use it for the body of every sheet whose content can grow; a sticky
 * `SheetHeader` and a footer stay outside it and keep their place.
 */
export function SheetBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex-1 min-h-0 overflow-y-auto", className)}
      {...props}
    />
  );
}

/**
 * Action bar at the bottom of a `Sheet`: separator, padding, safe area, and
 * a place that never scrolls away.
 *
 * Hand-rolled, this row was written thirteen ways — `p-6 border-t bg-surface`,
 * `p-8 bg-surface border-t`, `px-5 pt-3 pb-[calc(1.5rem+env(…))]`, and once
 * `pb-safe-bottom`, which is not a utility this project defines and therefore
 * did nothing at all. The bottom inset is the part worth centralising: it is
 * invisible on a desktop and on the simulator, so a footer that forgets it is
 * only wrong on the hardware nobody tests on.
 *
 * Put the buttons in a `SheetActions` inside it; anything else in the footer
 * (a hint, a second row, a destructive action set apart from the rest) is a
 * sibling of that row.
 */
export function SheetFooter({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "shrink-0 border-t border-border bg-surface-card",
        "px-4 pt-3 pb-[calc(env(safe-area-inset-bottom)+0.75rem)] sm:px-5",
        className,
      )}
      {...props}
    />
  );
}

/**
 * The row of buttons in a footer: full width on a phone, intrinsic width and
 * aligned to the end from `sm:` up.
 *
 * The widths are declared here, on the row, rather than by each button —
 * because when the call site declared them it wrote `flex-1` and stopped.
 * That half of the rule is the phone layout; without the `sm:` half a dialog
 * on a desktop is split down the middle and Cancel carries the same weight as
 * Save, which UI_GUIDELINES §4.3 asks it not to. The rule cannot be forgotten
 * if the call site does not state it.
 *
 * A child that must keep its own width (an icon button, a link styled as one)
 * says so with `!flex-none` — the row's selector outranks a plain utility.
 * Content that belongs on the left, like a count of what is about to be
 * saved, takes `mr-auto`.
 */
export function SheetActions({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2",
        "[&>button]:flex-1 sm:[&>button]:flex-initial",
        className,
      )}
      {...props}
    />
  );
}

interface SheetHeaderProps {
  /** Heading text. Rendered inside a `SheetTitle`. */
  title?: React.ReactNode;
  /** When provided, renders the trailing close button. */
  onClose?: () => void;
  /**
   * Accessible name for the close button.
   * Defaults to `common:a11y.close`.
   */
  closeLabel?: string;
  /** Extra content between the title and the close button. */
  children?: React.ReactNode;
  /** Overrides the default padding/border. */
  className?: string;
}

/**
 * Title row for a `Sheet`: heading on the left, close button on the right.
 *
 * Replaces the hand-rolled `<div className="flex items-center justify-between">`
 * + `<h2>` + ghost `<Button>` block that every sheet repeated. Defaults match
 * the most common existing spelling (`p-5`, bottom border); pass `className`
 * where a sheet needs different padding.
 */
export function SheetHeader({
  title,
  onClose,
  closeLabel,
  children,
  className,
}: SheetHeaderProps) {
  const { t } = useTranslation("common");

  return (
    <div
      className={cn(
        "flex items-center justify-between border-b border-border p-5",
        className,
      )}
    >
      {title !== undefined && <SheetTitle>{title}</SheetTitle>}
      {children}
      {onClose && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={closeLabel ?? t("a11y.close")}
          className="rounded-full text-on-muted"
        >
          <X size={20} />
        </Button>
      )}
    </div>
  );
}
