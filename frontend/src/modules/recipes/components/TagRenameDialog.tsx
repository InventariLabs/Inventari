import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";

interface Props {
  /** The tag being renamed, or null when the dialog is closed. */
  name: string | null;
  onCancel: () => void;
  onConfirm: (name: string, next: string) => void;
}

/** Asks for the new name of a tag. */
export function TagRenameDialog({ name, onCancel, onConfirm }: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const [next, setNext] = useState("");

  useEffect(() => {
    setNext(name ?? "");
  }, [name]);

  const trimmed = next.trim();

  return (
    <ConfirmDialog
      open={name !== null}
      title={t("recipes:tags_manager.rename_title")}
      message=""
      confirmLabel={t("recipes:tags_manager.rename")}
      cancelLabel={t("common:actions.cancel")}
      confirmDisabled={trimmed === "" || trimmed === name}
      onConfirm={() => name && onConfirm(name, trimmed)}
      onCancel={onCancel}
    >
      <Input
        label={t("recipes:tags_manager.rename_label")}
        autoFocus
        value={next}
        onChange={(e) => setNext(e.target.value)}
      />
    </ConfirmDialog>
  );
}
