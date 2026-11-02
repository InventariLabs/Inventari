import { useCallback, useState } from "react";
import { useFormGuard } from "@/hooks/useFormGuard";

/**
 * The question a sheet asks before it throws away what was typed into it.
 *
 * Escape, the close button, a click on the backdrop and the cancel button all
 * reach the same exit, so they all go through `requestClose`: a clean form
 * closes at once, a filled-in one raises the question and stays open until the
 * reader answers. Render `DiscardDraftDialog` with `dialogProps` beside the
 * sheet.
 *
 * A filled-in sheet is also reported to the shell-wide navigation gate under
 * `label` (already localized): the app header reaches above the overlay's
 * edge, so a click on the logo, the settings link or the command palette is an
 * exit that never passes through `requestClose`.
 */
export function useDiscardGuard(
  isDirty: boolean,
  onClose: () => void,
  label: string,
) {
  useFormGuard(isDirty, label);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const requestClose = useCallback(() => {
    if (isDirty) {
      setConfirmOpen(true);
      return;
    }
    onClose();
  }, [isDirty, onClose]);

  const dialogProps = {
    open: confirmOpen,
    onConfirm: () => {
      setConfirmOpen(false);
      onClose();
    },
    onCancel: () => setConfirmOpen(false),
  };

  return { requestClose, dialogProps };
}
