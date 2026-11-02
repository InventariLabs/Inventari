import * as React from "react";
import * as AlertDialogPrimitive from "@radix-ui/react-alert-dialog";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { extractApiError, readableErrorMessage } from "@/lib/errors";
import { Button, buttonVariants } from "@/components/ui/Button";
import { AlertTriangle } from "lucide-react";
import { getTopmostOverlaySheetPanel } from "./overlayStack";

const AlertDialog = AlertDialogPrimitive.Root;

const AlertDialogTrigger = AlertDialogPrimitive.Trigger;

/**
 * The layer this dialog stands on.
 *
 * "confirm" (UI_GUIDELINES §4.1) is above the modals it is normally raised
 * from. A question asked by a surface on the fullscreen layer needs that
 * layer instead: pinned to `--z-confirm` it would render *behind* the wizard
 * that raised it — invisible, and modal all the same, which is the worst of
 * both. Radix portals it to the end of `body`, so equal tiers paint in that
 * order and the question lands on top of the surface asking it.
 */
type ConfirmDialogZTier = "confirm" | "fullscreen";

const zTierVar: Record<ConfirmDialogZTier, string> = {
  confirm: "var(--z-confirm)",
  fullscreen: "var(--z-fullscreen)",
};

const AlertDialogContent = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Content> & {
    zIndex?: ConfirmDialogZTier;
  }
>(({ className, zIndex = "confirm", ...props }, ref) => (
  <AlertDialogPrimitive.Portal>
    <AlertDialogPrimitive.Overlay
      className="fixed inset-0 bg-black/50 animate-in fade-in duration-150"
      style={{ zIndex: zTierVar[zIndex] }}
    />
    <AlertDialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed left-1/2 top-1/2 w-full max-w-md -translate-x-1/2 -translate-y-1/2 bg-surface-card rounded-2xl shadow-xl p-6 space-y-4 animate-in zoom-in-95 duration-200",
        className,
      )}
      style={{ zIndex: zTierVar[zIndex] }}
      {...props}
    />
  </AlertDialogPrimitive.Portal>
));
AlertDialogContent.displayName = AlertDialogPrimitive.Content.displayName;

const AlertDialogHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col gap-1.5", className)} {...props} />
);
AlertDialogHeader.displayName = "AlertDialogHeader";

const AlertDialogTitle = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Title
    ref={ref}
    className={cn("text-base font-semibold text-on", className)}
    {...props}
  />
));
AlertDialogTitle.displayName = AlertDialogPrimitive.Title.displayName;

const AlertDialogDescription = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Description
    ref={ref}
    className={cn("text-sm text-on-secondary", className)}
    {...props}
  />
));
AlertDialogDescription.displayName =
  AlertDialogPrimitive.Description.displayName;

const AlertDialogFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex justify-end gap-3 pt-2", className)} {...props} />
);
AlertDialogFooter.displayName = "AlertDialogFooter";

const AlertDialogAction = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Action>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Action>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Action
    ref={ref}
    className={cn(buttonVariants(), className)}
    {...props}
  />
));
AlertDialogAction.displayName = AlertDialogPrimitive.Action.displayName;

const AlertDialogCancel = React.forwardRef<
  React.ElementRef<typeof AlertDialogPrimitive.Cancel>,
  React.ComponentPropsWithoutRef<typeof AlertDialogPrimitive.Cancel>
>(({ className, ...props }, ref) => (
  <AlertDialogPrimitive.Cancel
    ref={ref}
    className={cn(buttonVariants({ variant: "secondary" }), className)}
    {...props}
  />
));
AlertDialogCancel.displayName = AlertDialogPrimitive.Cancel.displayName;

const isPromise = (value: unknown): value is Promise<unknown> =>
  typeof (value as { then?: unknown })?.then === "function";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "default";
  /** When true, only the cancel button is rendered (informational dialogs). */
  hideConfirm?: boolean;
  /**
   * Blocks confirming while the dialog still needs an answer from the user —
   * a target to move items to, a reason, a typed-out name.
   */
  confirmDisabled?: boolean;
  /**
   * The operation to run. Returning a promise changes what the dialog does
   * with it: instead of closing on the click, it waits, and a rejection keeps
   * the dialog open with the fields as typed and the reason shown inside it.
   *
   * A dialog that closed on failure looked exactly like one that succeeded —
   * the typed reason and note were gone, the delete had not happened, and the
   * only trace was a toast on its way out.
   *
   * Reject with a `ReadableError` when the server said `200` and still did
   * nothing the reader asked for; its message is shown as written instead of
   * being put through `extractApiError`.
   */
  onConfirm: () => unknown;
  /** What to say when the operation fails and the API sends no reason. */
  errorFallback?: string;
  onCancel: () => void;
  children?: React.ReactNode;
  /**
   * Which layer the question is asked on (UI_GUIDELINES §4.1). Leave it at
   * "confirm" for a dialog raised from a modal; a surface on the fullscreen
   * layer passes "fullscreen", or the question renders behind it.
   */
  zIndex?: ConfirmDialogZTier;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  variant = "default",
  hideConfirm = false,
  confirmDisabled = false,
  onConfirm,
  errorFallback,
  onCancel,
  children,
  zIndex = "confirm",
}: ConfirmDialogProps) {
  const { t } = useTranslation("common");
  // Audit note (PL): the shared dialog had hardcoded English defaults —
  // resolve them through i18n so every confirm dialog follows the UI
  // language, not just the ones passing explicit labels.
  const confirmText = confirmLabel ?? t("actions.confirm");
  const cancelText = cancelLabel ?? t("actions.cancel");

  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // The element focus came from, captured while the question opens — before
  // Radix moves focus into it. Its own default is to hand the focus back to
  // that element, which is only useful while the element still exists: a
  // question asked from a list that closed meanwhile left the reader on
  // `body`, outside the sheet, where the next Tab walks the page behind it.
  const restoreFocusTo = React.useRef<HTMLElement | null>(null);
  // A synchronous confirm lets Radix close the dialog on the same click, and
  // that close arrives through onOpenChange like any other. It is an answer,
  // not a dismissal — onCancel means the reader left the question unanswered
  // (Escape, the cancel button), so a close the confirm caused is not one.
  //
  // The suppression window is exactly the confirming click, not "until the
  // dialog closes": a synchronous confirm can also start work whose close
  // rides on a later success (a mutation that closes in onSuccess). When that
  // work fails the dialog stays open, and a flag still held from the confirm
  // would swallow the next cancel too — a modal question with no way out.
  const answeredRef = React.useRef(false);
  // The focus hand-back is delayed work on the global timer queue: the id
  // lives in a ref and unmount takes it back, so the restore never fires on
  // an environment that has already been torn down.
  const focusTimerRef = React.useRef<number | null>(null);
  // Radix reports the close on a task of its own, so that report can arrive
  // after unmount — past the cleanup below. A timer started then has no owner.
  const mountedRef = React.useRef(true);

  // A reopened dialog starts clean: last time's failure is not this time's,
  // and neither is last time's answer.
  React.useEffect(() => {
    if (!open) {
      setBusy(false);
      setError(null);
    } else {
      answeredRef.current = false;
    }
  }, [open]);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (focusTimerRef.current !== null) {
        clearTimeout(focusTimerRef.current);
        focusTimerRef.current = null;
      }
    };
  }, []);

  const handleOpenAutoFocus = () => {
    restoreFocusTo.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
  };

  const handleCloseAutoFocus = (event: Event) => {
    const previous = restoreFocusTo.current;
    restoreFocusTo.current = null;
    // Radix hands the focus back on a task of its own, not inside the click;
    // doing this work synchronously in the unmount path moved it in front of
    // the flush a navigation rides on. The target is ours, the timing is the
    // primitive's.
    event.preventDefault();
    if (!mountedRef.current) return;
    if (focusTimerRef.current !== null) {
      clearTimeout(focusTimerRef.current);
    }
    focusTimerRef.current = window.setTimeout(() => {
      focusTimerRef.current = null;
      if (previous && previous !== document.body && previous.isConnected) {
        previous.focus();
        return;
      }
      // The element is gone. The sheet under the question is the nearest thing
      // the reader was working in; its panel takes the focus (`tabIndex={-1}`).
      getTopmostOverlaySheetPanel()?.focus();
    }, 0);
  };

  const handleConfirm = (event: React.MouseEvent) => {
    const returned: unknown = onConfirm();
    if (!isPromise(returned)) {
      // Radix closes on this click; mark the answer first, so the close does
      // not read as a cancellation. The mark holds for this click only — the
      // close it excuses arrives synchronously within the same task, and any
      // later close is a separate action the reader took on a question that
      // stayed open, which is a cancellation again.
      answeredRef.current = true;
      queueMicrotask(() => {
        answeredRef.current = false;
      });
      return;
    }
    const result = returned;
    // Synchronous, before the await: Radix closes the dialog on this click
    // unless the default is prevented here.
    event.preventDefault();
    setBusy(true);
    setError(null);
    result
      .then(() => setBusy(false))
      .catch((cause: unknown) => {
        setBusy(false);
        setError(
          readableErrorMessage(cause) ??
            extractApiError(cause, errorFallback ?? t("errors.actionFailed")),
        );
      });
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(isOpen) => {
        if (isOpen || answeredRef.current) return;
        onCancel();
      }}
    >
      <AlertDialogContent
        zIndex={zIndex}
        onOpenAutoFocus={handleOpenAutoFocus}
        onCloseAutoFocus={handleCloseAutoFocus}
      >
        <AlertDialogHeader>
          {(variant === "danger" || variant === "warning") && (
            <div
              className={cn(
                "shrink-0 w-10 h-10 rounded-full flex items-center justify-center self-start",
                variant === "danger" ? "bg-red-100" : "bg-amber-100",
              )}
            >
              <AlertTriangle
                size={20}
                className={
                  variant === "danger"
                    ? "text-red-600 dark:text-red-400"
                    : "text-amber-600 dark:text-amber-400"
                }
              />
            </div>
          )}
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{message}</AlertDialogDescription>
          {children && <div className="space-y-3 mt-2">{children}</div>}
          {error && (
            <p
              role="alert"
              className="mt-2 rounded-lg bg-red-50 dark:bg-red-900/20 px-3 py-2 text-sm text-red-700 dark:text-red-400"
            >
              {error}
            </p>
          )}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel asChild>
            <Button variant="secondary" disabled={busy}>
              {cancelText}
            </Button>
          </AlertDialogCancel>
          {!hideConfirm && (
            <AlertDialogAction
              asChild
              className={
                variant === "danger"
                  ? "bg-red-600 hover:bg-red-700 text-white"
                  : variant === "warning"
                    ? "bg-amber-600 hover:bg-amber-700 text-white"
                    : ""
              }
            >
              <Button
                variant="default"
                disabled={confirmDisabled}
                isLoading={busy}
                onClick={handleConfirm}
              >
                {confirmText}
              </Button>
            </AlertDialogAction>
          )}
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export {
  AlertDialog,
  AlertDialogTrigger,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
};
