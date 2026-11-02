import { useState, useCallback } from "react";

interface ConfirmState {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "default";
  /** Informational dialog: no confirm button, only the dismissal. */
  hideConfirm?: boolean;
  resolve?: (value: boolean) => void;
  onConfirmCallback?: () => void;
}

export function useConfirm() {
  const [state, setState] = useState<ConfirmState>({
    open: false,
    title: "",
    message: "",
  });

  const confirm = useCallback(
    (opts: {
      title: string;
      message: string;
      confirmLabel?: string;
      cancelLabel?: string;
      variant?: "danger" | "default";
      hideConfirm?: boolean;
    }): Promise<boolean> => {
      return new Promise((resolve) => {
        setState({ ...opts, open: true, resolve });
      });
    },
    [],
  );

  const onConfirm = useCallback(() => {
    state.resolve?.(true);
    state.onConfirmCallback?.();
    setState((s) => ({ ...s, open: false }));
  }, [state]);

  const onCancel = useCallback(() => {
    state.resolve?.(false);
    setState((s) => ({ ...s, open: false }));
  }, [state]);

  return {
    confirm,
    confirmDialogProps: {
      open: state.open,
      title: state.title,
      message: state.message,
      confirmLabel: state.confirmLabel,
      cancelLabel: state.cancelLabel,
      variant: state.variant,
      hideConfirm: state.hideConfirm,
      onConfirm,
      onCancel,
    },
  };
}

export interface ConfirmDialogState {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "warning" | "default";
  /** Hand it to `ConfirmDialog` as is: the dialog closes when the action
   * has gone through, and stays open with the reason when it is refused. */
  onConfirm: () => unknown;
}

export function useConfirmDialog() {
  const [dialogState, setDialogState] = useState<ConfirmDialogState>({
    isOpen: false,
    title: "",
    message: "",
    onConfirm: () => {},
  });

  const showConfirm = useCallback(
    (options: Omit<ConfirmDialogState, "isOpen">) => {
      return new Promise<boolean>((resolve) => {
        setDialogState({
          ...options,
          isOpen: true,
          // The action's promise goes back to the dialog: dropping it here
          // closed the question on a refusal and said nothing.
          onConfirm: async () => {
            await options.onConfirm();
            setDialogState((prev) => ({ ...prev, isOpen: false }));
            resolve(true);
          },
        });
      });
    },
    [],
  );

  const closeDialog = useCallback(() => {
    setDialogState((prev) => ({ ...prev, isOpen: false }));
  }, []);

  return {
    dialogState,
    showConfirm,
    closeDialog,
  };
}
