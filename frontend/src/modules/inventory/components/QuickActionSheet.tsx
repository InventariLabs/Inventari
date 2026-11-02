import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { formatDate, isExpired, isExpiringSoon } from "@/utils/helpers";
import { effectiveExpiry } from "@/utils/effectiveExpiry";
import {
  X,
  Package,
  Calendar,
  AlertTriangle,
  Barcode,
  Edit2,
  FileText,
} from "lucide-react";
import type { Item } from "@/types";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { Slot } from "@/components/Slot";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useItemQuickActions } from "@/modules/inventory/hooks/useItemQuickActions";
import { QuickActionGrid } from "./QuickActionGrid";
import { DeleteReasonDialog } from "./DeleteReasonDialog";

interface Props {
  item: Item;
  onClose: () => void;
  onViewDetails?: () => void;
  onMove?: () => void;
}

export default function QuickActionSheet({
  item,
  onClose,
  onViewDetails,
  onMove,
}: Props) {
  const { t } = useTranslation(["labels", "common", "items", "equipment"]);
  const navigate = useNavigate();
  // The grid above comes from a hook that asks the same question, but this
  // button was written beside it without one: a reader's shortcut offered
  // "Edit" and opened the full form, which the API then refused at Save.
  const canWrite = useCanWrite("items");
  const { actions, deleteDialog } = useItemQuickActions(item, {
    onDone: onClose,
    onMove: () => {
      if (onMove) onMove();
      else if (onViewDetails) onViewDetails();
    },
  });

  const expiry = effectiveExpiry(item);
  const expired = isExpired(expiry);
  const expiringSoon = isExpiringSoon(expiry);

  return (
    <Sheet open onClose={onClose} backdropOpacity={60} aria-label={item.name}>
      {/* Drag Handle for mobile feel */}
      <div className="w-12 h-1.5 bg-surface-inset rounded-full mx-auto mt-3 mb-1 sm:hidden"></div>

      <div className="p-6 flex-1 overflow-y-auto">
        <div className="flex justify-between items-start mb-6">
          <div className="flex items-center gap-4">
            {item.image_url ? (
              <img
                src={item.image_url}
                alt={`Product image ${item.name}`}
                loading="lazy"
                className="w-14 h-14 rounded-xl object-cover border shadow-sm"
              />
            ) : (
              <div className="w-14 h-14 bg-surface-raised rounded-xl flex items-center justify-center text-on-muted border">
                <Package size={28} />
              </div>
            )}
            <div>
              <h3 className="font-semibold text-lg text-on leading-tight">
                {item.name}
              </h3>
              <p className="text-on-secondary text-sm mt-0.5">
                {item.brand || t("items:noBrand")}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:a11y.close")}
          >
            <X size={24} />
          </Button>
        </div>

        {/* Status Badges */}
        <div className="flex flex-wrap gap-2 mb-6">
          <div className="px-3 py-1 bg-surface-raised text-on-secondary rounded-full text-xs font-medium flex items-center gap-1.5">
            <Package size={12} />
            {formatQuantityLocalized(t, item.quantity, item.uom?.symbol)}
          </div>
          {item.barcode && (
            <div className="px-3 py-1 bg-surface-raised text-on-secondary rounded-full text-xs font-semibold flex items-center gap-1.5 font-mono">
              <Barcode size={12} />
              {item.barcode}
            </div>
          )}
          {expiry && (
            <div
              className={`px-3 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 ${
                expired
                  ? "bg-red-100 text-red-700"
                  : expiringSoon
                    ? "bg-orange-100 text-orange-700"
                    : "bg-primary-100 text-primary-700"
              }`}
            >
              <Calendar size={12} />
              {formatDate(expiry)}
              {expired && <AlertTriangle size={12} />}
            </div>
          )}
        </div>

        {/* Modular Slot for Nutrition Summary, etc. */}
        <Slot name="quick_action_extra" data={{ item }} className="mb-6" />

        {/* Action Grid */}
        <QuickActionGrid actions={actions} />

        {/* The sheet is the shortcut from the list; the page is where the
            record answers questions the sheet was not asked. */}
        <Button
          variant="outline"
          onClick={() => {
            onClose();
            navigate(`/inventory/items/${item.id}`);
          }}
          className="w-full mt-6"
        >
          <FileText size={18} />
          {t("items:detail.viewDetails")}
        </Button>

        {canWrite && (
          <Button
            variant="outline"
            onClick={() => {
              if (onViewDetails) onViewDetails();
              else onClose();
            }}
            className="w-full mt-2"
          >
            <Edit2 size={18} />
            {t("common:actions.edit")}
          </Button>
        )}
      </div>

      <DeleteReasonDialog
        key={String(deleteDialog.open)}
        open={deleteDialog.open}
        itemName={item.name}
        onConfirm={deleteDialog.onConfirm}
        onCancel={deleteDialog.onCancel}
      />
    </Sheet>
  );
}
