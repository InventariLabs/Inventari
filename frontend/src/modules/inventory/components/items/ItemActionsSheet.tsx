import { useTranslation } from "react-i18next";
import {
  Bell,
  CheckCircle,
  Edit2,
  FileText,
  Move,
  Plus,
  Trash2,
} from "lucide-react";
import Button from "@/components/ui/Button";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { isInVirtualPlace } from "@/modules/shared/lib/storageUsage";
import type { Item, StorageLocationSummary } from "@/types";

interface ItemActionsSheetProps {
  item: Item;
  open: boolean;
  onClose: () => void;
  /** The row's stock actions, spelled out for the finger a tooltip never reaches. */
  onConsume: (itemId: string) => void;
  onAddOne: (itemId: string) => void;
  onEdit: (item: Item) => void;
  /** Opens the product page — history, movements and Print label live there. */
  onViewDetails: (item: Item) => void;
  onMove: (item: Item) => void;
  onSetThreshold: (item: Item) => void;
  onDelete?: (itemId: string) => void;
  /** Where the record stands: in a system place no unit can be added. */
  storages?: StorageLocationSummary[];
  /** Whether to offer any of them — edit, move and the alert all write. */
  canWrite?: boolean;
  /** Whether Delete may be offered — the API checks `items:delete` for it. */
  canDelete?: boolean;
}

/**
 * the per-row ⋮ used to replay the row tap — a control that promised
 * a menu and never opened one. It opens this sheet now. Order is safest
 * first; Delete sits below a divider and carries its danger in the label
 * colour (ghostDanger, UI_GUIDELINES §2.13a), and routes through the page's
 * ConfirmDialog rather than deleting on tap.
 *
 * "Product details" leads the sheet: the row itself opens the Edit form, so
 * without this entry the product page (history, movements, labels) has no door
 * from the list. The stock actions have two doors too: the row carries them as
 * icons — check circle, + — whose words live in a tooltip no finger ever
 * sees, so the menu spells the same actions out. Reading what a tap does to
 * the stock is worth a second door.
 *
 * "Move" is here because it was nowhere: the sheet that changes an item's
 * location was written, tested and never opened by anything, leaving bulk edit
 * on a single selected row as the only way to move one item.
 */
export default function ItemActionsSheet({
  item,
  open,
  onClose,
  onConsume,
  onAddOne,
  onEdit,
  onViewDetails,
  onMove,
  onSetThreshold,
  onDelete,
  storages,
  canWrite = true,
  canDelete = canWrite,
}: ItemActionsSheetProps) {
  const { t } = useTranslation(["items", "common", "labels"]);
  const usedUp = isInVirtualPlace(item.location_id, storages);
  return (
    <Sheet open={open} onClose={onClose} aria-label={item.name}>
      {/* The name in aria-label is read to a screen reader; the reader
          looking at the screen had nothing. Three rows can share one name,
          so the sheet says whose it is — the row that opened it. */}
      <SheetHeader title={item.name} onClose={onClose} />
      <SheetBody className="flex flex-col gap-2 p-2">
        <Button
          variant="ghost"
          className="w-full justify-start"
          leftIcon={<FileText size={16} />}
          onClick={() => {
            onClose();
            onViewDetails(item);
          }}
        >
          {t("items:detail.viewDetails")}
        </Button>
        {canWrite && (
          <>
            {/* The same words the row's icons carry in their names and
                tooltips — one vocabulary for the same two actions. */}
            <Button
              variant="ghost"
              className="w-full justify-start"
              leftIcon={<CheckCircle size={16} />}
              onClick={() => {
                onClose();
                onConsume(item.id);
              }}
            >
              {t("items:actions.consume1unit")}
            </Button>
            {!usedUp && (
              <Button
                variant="ghost"
                className="w-full justify-start"
                leftIcon={<Plus size={16} />}
                onClick={() => {
                  onClose();
                  onAddOne(item.id);
                }}
              >
                {t("items:actions.addOneUnit")}
              </Button>
            )}
            <Button
              variant="ghost"
              className="w-full justify-start"
              leftIcon={<Edit2 size={16} />}
              onClick={() => {
                onClose();
                onEdit(item);
              }}
            >
              {t("items:actions.edit")}
            </Button>
            <Button
              variant="ghost"
              className="w-full justify-start"
              leftIcon={<Move size={16} />}
              onClick={() => {
                onClose();
                onMove(item);
              }}
            >
              {t("items:quickActions.move")}
            </Button>
            <Button
              variant="ghost"
              className="w-full justify-start"
              leftIcon={<Bell size={16} />}
              onClick={() => {
                onClose();
                onSetThreshold(item);
              }}
            >
              {t("items:setStockAlert")}
            </Button>
          </>
        )}
        {canDelete && onDelete && (
          <>
            <div aria-hidden="true" className="mx-2 h-px bg-border" />
            <Button
              variant="ghostDanger"
              className="w-full justify-start"
              leftIcon={<Trash2 size={16} />}
              onClick={() => {
                onClose();
                onDelete(item.id);
              }}
            >
              {t("common:actions.delete")}
            </Button>
          </>
        )}
      </SheetBody>
    </Sheet>
  );
}
