import { AlertTriangle, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { Sheet, SheetBody } from "@/components/ui/Sheet";

export interface WmsStartFailureProps {
  /** What went wrong, in the reader's language. */
  message: string;
  /** Accessible name for the dialog. */
  dialogLabel: string;
  closeLabel: string;
  onClose: () => void;
  /** Omitted when retrying cannot work — a refusal only repeats itself. */
  retry?: { label: string; onRetry: () => void };
  requestApproval?: { label: string; onRequest: () => void };
  /**
   * The ways out when the document is held by someone else's session, the
   * holder named in both labels. Taking over keeps the scans already made;
   * releasing goes through the release door and discards them, and its label
   * says so. Without them the refusal is a dead end — the document waits for
   * a holder who walked away.
   */
  heldSession?: {
    owner: string;
    onTakeOver: () => void | Promise<void>;
    onRelease: () => void | Promise<void>;
  };
  /** A refusal is not a malfunction, and the picture should not say it is. */
  refused?: boolean;
}

/**
 * A scanning session that would not start, said where the reader is looking.
 *
 * Both WMS views returned a bare `<div>` for this, and `DocumentDetailModals`
 * renders them inline — so on a document of any length the message landed
 * below the line table and the totals card, 1291 px down a 1427 px page. The
 * reader tapped "Scan receiving", nothing appeared to happen, and the
 * explanation was somewhere off the bottom of the screen.
 *
 * The active session is a `Sheet`; this is the same, because it answers the
 * same tap. The second half is the retry: offering it after a 403 gives the
 * reader a button whose only possible outcome is the refusal they just had.
 */
export function WmsStartFailure({
  message,
  dialogLabel,
  closeLabel,
  onClose,
  retry,
  requestApproval,
  heldSession,
  refused = false,
}: WmsStartFailureProps) {
  const { t } = useTranslation("warehouse");
  const Icon = refused ? Lock : AlertTriangle;
  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="sm"
      aria-label={dialogLabel}
    >
      {/* A refusal in German wraps to three lines on a phone; the panel is
          `overflow-hidden`, so the body needs a scrolling region of its own. */}
      <SheetBody
        role="alert"
        className="flex flex-col items-center justify-center gap-3 p-8 text-center"
      >
        <Icon
          className={
            refused ? "w-8 h-8 text-on-muted" : "w-8 h-8 text-amber-500"
          }
          aria-hidden="true"
        />
        <p className="text-sm text-on-secondary max-w-sm">{message}</p>
        <div className="flex flex-wrap justify-center gap-2">
          {heldSession && (
            <>
              <Button size="sm" onClick={() => void heldSession.onTakeOver()}>
                {t("scanSession.takeOver", { owner: heldSession.owner })}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void heldSession.onRelease()}
              >
                {t("scanSession.discardAndStart", { owner: heldSession.owner })}
              </Button>
            </>
          )}
          {requestApproval && (
            <Button size="sm" onClick={requestApproval.onRequest}>
              {requestApproval.label}
            </Button>
          )}
          {retry && (
            <Button size="sm" variant="outline" onClick={retry.onRetry}>
              {retry.label}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onClose}>
            {closeLabel}
          </Button>
        </div>
      </SheetBody>
    </Sheet>
  );
}
