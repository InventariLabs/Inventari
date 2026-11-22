import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Edit2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ConsumeDialog } from "@/modules/inventory/components/ConsumeDialog";
import { DeleteReasonDialog } from "@/modules/inventory/components/DeleteReasonDialog";
import { MoveItemModal } from "@/modules/inventory/components/MoveItemModal";
import { useItemQuickActions } from "@/modules/inventory/hooks/useItemQuickActions";
import type { Item } from "@/types";

interface ItemDetailActionsProps {
  item: Item;
  /** The record stands in a system place, where no unit can be added. */
  inVirtualPlace: boolean;
  onEdit: () => void;
  /** The record is gone, and the address of its page with it. */
  onDeleted: () => void;
}

/**
 * The product page's actions, in the page header: the stock actions the sheet
 * over the list offers, then Edit, the page's main action, and the
 * destructive one last, behind a divider (UI_GUIDELINES §2.13a, §11.4). They
 * are the app's ordinary buttons; the coloured bars belong to the sheet.
 *
 * The component owns the actions and the dialogs they open, which cover the
 * whole page from inside the header: consume and delete render in a portal,
 * the move sheet as a fixed overlay. The page
 * hands the shell this element once per record, and a pending press
 * re-renders it here rather than re-setting the header on every render.
 *
 * Every action writes, so the component asks for itself and offers nothing to
 * an account that cannot write, wherever it is mounted.
 */
export function ItemDetailActions({
  item,
  inVirtualPlace,
  onEdit,
  onDeleted,
}: ItemDetailActionsProps) {
  const { t } = useTranslation(["common"]);
  const canWrite = useCanWrite("items");
  const [moving, setMoving] = useState(false);
  const { actions, deleteDialog, consumeDialog } = useItemQuickActions(item, {
    onDone: () => {},
    onMove: () => setMoving(true),
    onDeleted,
    inVirtualPlace,
  });
  if (!canWrite) return null;
  const regular = actions.filter((action) => !action.danger);
  const destructive = actions.filter((action) => action.danger);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {regular.map((action) => (
        <Button
          key={action.id}
          variant="outline"
          leftIcon={<action.icon size={16} />}
          onClick={action.onClick}
          isLoading={action.isLoading}
          disabled={action.disabled}
        >
          {action.label}
        </Button>
      ))}
      <Button variant="primary" leftIcon={<Edit2 size={16} />} onClick={onEdit}>
        {t("common:actions.edit")}
      </Button>
      {destructive.length > 0 && (
        <>
          <span aria-hidden="true" className="w-px h-5 shrink-0 bg-border" />
          {destructive.map((action) => (
            <Button
              key={action.id}
              variant="ghostDanger"
              leftIcon={<action.icon size={16} />}
              onClick={action.onClick}
              isLoading={action.isLoading}
              disabled={action.disabled}
            >
              {action.label}
            </Button>
          ))}
        </>
      )}

      <ConsumeDialog
        key={consumeDialog.item?.id ?? "closed"}
        open={consumeDialog.item !== null}
        item={consumeDialog.item}
        onConfirm={consumeDialog.onConfirm}
        onCancel={consumeDialog.onCancel}
      />

      <DeleteReasonDialog
        key={String(deleteDialog.open)}
        open={deleteDialog.open}
        itemName={item.name}
        onConfirm={deleteDialog.onConfirm}
        onCancel={deleteDialog.onCancel}
      />

      {moving && (
        <MoveItemModal
          item={item}
          onClose={() => setMoving(false)}
          onSuccess={() => setMoving(false)}
        />
      )}
    </div>
  );
}
