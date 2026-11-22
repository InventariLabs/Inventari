import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";

interface Props {
  /** The tag being renamed, or null when the dialog is closed. */
  name: string | null;
  onCancel: () => void;
  /** Runs the rename; a rejection keeps the dialog open with the reason. */
  onConfirm: (name: string, next: string) => Promise<unknown>;
  /** Names of the tags that exist now — a rename onto one of them merges. */
  existing?: readonly string[];
}

/** Asks for the new name of a tag. */
export function TagRenameDialog({
  name,
  onCancel,
  onConfirm,
  existing = [],
}: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const [next, setNext] = useState("");

  useEffect(() => {
    setNext(name ?? "");
  }, [name]);

  const trimmed = next.trim();
  // A rename travels as a merge: onto a name another tag has, the two become one.
  const merges = trimmed !== name && existing.includes(trimmed);

  return (
    <ConfirmDialog
      open={name !== null}
      title={t("recipes:tags_manager.rename_title")}
      message=""
      confirmLabel={t("recipes:tags_manager.rename")}
      cancelLabel={t("common:actions.cancel")}
      confirmDisabled={trimmed === "" || trimmed === name}
      errorFallback={t("recipes:tags_manager.rename_failed")}
      onConfirm={() => (name ? onConfirm(name, trimmed) : undefined)}
      onCancel={onCancel}
    >
      <Input
        label={t("recipes:tags_manager.rename_label")}
        autoFocus
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
      {merges && (
        <p role="status" className="text-sm text-on-secondary">
          {t("recipes:tags_manager.rename_merges", { name: trimmed })}
        </p>
      )}
    </ConfirmDialog>
  );
}
