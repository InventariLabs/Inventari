import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

interface Props<L extends { id: string; product_name?: string | null }> {
  /** The line the worker asked to skip; the dialog is open while it is set. */
  line: L | null;
  title: string;
  message: (product: string) => string;
  confirmLabel: string;
  onConfirm: (line: L) => void;
  onCancel: () => void;
}

/**
 * The question a picking or receiving session asks before it skips a line.
 *
 * A skip leaves the line unresolved and was one tap from the row. It asks no
 * reason, unlike a shortfall: the server keeps none for a skip, and the line
 * stays on the list with an Undo.
 */
export function WmsSkipConfirm<
  L extends { id: string; product_name?: string | null },
>({ line, title, message, confirmLabel, onConfirm, onCancel }: Props<L>) {
  return (
    <ConfirmDialog
      open={line !== null}
      title={title}
      message={message(line?.product_name ?? "")}
      confirmLabel={confirmLabel}
      onConfirm={() => {
        if (line) onConfirm(line);
      }}
      onCancel={onCancel}
    />
  );
}
