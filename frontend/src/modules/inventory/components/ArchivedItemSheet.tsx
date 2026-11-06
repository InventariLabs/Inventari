import { useTranslation } from "react-i18next";
import { History, RefreshCw, X, Calendar, CheckCircle2 } from "lucide-react";
import type { Item } from "@/types";
import { useUnassignLabel } from "@/modules/shared/hooks/useLabels";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { formatDate } from "@/utils/helpers";
import { archivedReasonLabel } from "@/modules/shared/lib/archiveReasons";

interface Props {
  item: Item;
  labelCode: string;
  onClose: () => void;
  onReuse: () => void;
  /** Whether to offer freeing the label — that unassigns it, which is a write. */
  canWrite?: boolean;
}

export default function ArchivedItemSheet({
  item,
  labelCode,
  onClose,
  onReuse,
  canWrite = true,
}: Props) {
  const { t } = useTranslation(["labels", "common", "inventory"]);
  const unassignMutation = useUnassignLabel();
  const handleUnassign = () => {
    unassignMutation.mutate(labelCode, {
      onSuccess: () => {
        toast.success(t("inventory:toasts.archivedLabelFreed"));
        onReuse();
      },
    });
  };

  return (
    <Sheet
      open
      onClose={onClose}
      backdropOpacity={60}
      aria-label={t("history.title", { defaultValue: "Product history" })}
    >
      <div className="w-12 h-1.5 bg-surface-inset rounded-full mx-auto mt-3 mb-1 sm:hidden"></div>

      <div className="p-6 flex-1 overflow-y-auto">
        <div className="flex justify-between items-start mb-6">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-primary-50 text-primary-600 rounded-xl flex items-center justify-center border border-primary-100 shadow-sm">
              <History size={28} />
            </div>
            <div>
              <h3 className="font-semibold text-lg text-on leading-tight">
                {t("history.title", { defaultValue: "Product history" })}
              </h3>
              <p className="text-on-secondary text-sm mt-0.5">
                {t("history.label", { defaultValue: "Label" })}:{" "}
                <span className="font-mono font-bold text-primary-600">
                  {labelCode}
                </span>
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label={t("common:actions.close")}
          >
            <X size={24} />
          </Button>
        </div>

        <div className="bg-amber-50 border border-amber-100 rounded-2xl p-5 mb-6">
          <p className="text-amber-900 text-sm leading-relaxed">
            {t("history.previouslyUsedFor", {
              defaultValue: "This label was previously used for:",
            })}
            <br />
            <span className="font-semibold text-base block mt-1">
              {item.name} {item.brand ? `(${item.brand})` : ""}
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-y-2 gap-x-4 mt-4 text-xs text-amber-700 font-medium">
            <div className="flex items-center gap-1">
              <CheckCircle2 size={14} />
              {t("history.status", { defaultValue: "Status" })}:{" "}
              {archivedReasonLabel(t, item.deletion_reason)}
            </div>
            {item.deleted_at && (
              <div className="flex items-center gap-1">
                <Calendar size={14} />
                {t("common:labels.date")}: {formatDate(item.deleted_at)}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3">
          {canWrite && (
            <Button
              onClick={() => handleUnassign()}
              disabled={unassignMutation.isPending}
              className="w-full"
            >
              {unassignMutation.isPending ? (
                <RefreshCw size={24} className="animate-spin" />
              ) : (
                <RefreshCw size={24} />
              )}
              {t("actions.reuseLabel", { defaultValue: "Reuse label" })}
            </Button>
          )}

          <Button variant="ghost" onClick={onClose} className="w-full">
            {t("common:actions.close")}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
