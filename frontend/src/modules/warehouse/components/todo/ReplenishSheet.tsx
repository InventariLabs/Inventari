import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { extractApiError } from "@/lib/errors";
import {
  usePostReplenishmentProposal,
  useReplenishmentProposal,
} from "@/modules/warehouse/hooks/useWorkItems";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import type { WorkItem } from "@/modules/warehouse/types";
import { workItemSentence } from "./workItemText";

/**
 * Filling a pick face from reserve: the transfer's lines, prepared by the
 * server, and the one button that posts them. Where the organization asks
 * for a shelf to be confirmed by scan, the reserve shelf must be scanned
 * before the move leaves it.
 */
export function ReplenishSheet({
  item,
  onClose,
}: {
  item: WorkItem;
  onClose: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const [scannedCode, setScannedCode] = useState("");
  const { data: profile } = useDocumentProfile();
  const {
    data: proposal,
    isLoading,
    isError,
    error,
    refetch,
  } = useReplenishmentProposal(item.source_id);
  const post = usePostReplenishmentProposal();
  const needsScan = profile?.confirm_shelf_by_scan === true;

  const submit = () =>
    post.mutate(
      {
        ruleId: item.source_id,
        scannedCode: needsScan ? scannedCode.trim() : undefined,
      },
      {
        onSuccess: (moved) => {
          toast.success(
            moved.status === "PENDING_APPROVAL"
              ? t("todo.replenishSheet.awaitingApproval", {
                  number: moved.number,
                })
              : t("todo.replenishSheet.done", { number: moved.number }),
          );
          onClose();
        },
        onError: (err) => {
          toast.error(extractApiError(err, t("todo.replenishSheet.failed")));
        },
      },
    );

  const lines = proposal?.lines ?? [];

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="sm"
      aria-label={t("todo.replenishSheet.title")}
    >
      <SheetHeader title={t("todo.replenishSheet.title")} onClose={onClose} />
      <SheetBody className="space-y-4 p-5">
        <p className="text-sm text-on">{workItemSentence(t, item)}</p>
        {isLoading && (
          <p className="text-sm text-on-secondary">
            {t("common:messages.loading")}
          </p>
        )}
        {isError && <InlineQueryError error={error} onRetry={refetch} />}
        {!isLoading && !isError && lines.length === 0 && (
          <p role="status" className="text-sm text-on-secondary">
            {t("todo.replenishSheet.expired")}
          </p>
        )}
        {lines.length > 0 && (
          <>
            <div className="text-xs uppercase tracking-widest text-on-muted">
              {t("todo.replenishSheet.lines")}
            </div>
            <ul className="divide-y divide-border rounded-lg border border-border">
              {lines.map((line) => (
                <li key={line.item_id} className="space-y-0.5 p-3 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium text-on">
                      {line.product_name}
                    </span>
                    <span className="tabular-nums text-on">
                      {formatQuantityLocalized(
                        t,
                        line.quantity,
                        line.uom_symbol,
                      )}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-x-3 text-xs text-on-secondary">
                    <span>
                      {t("todo.replenishSheet.from", {
                        location: line.source_location_name,
                      })}
                    </span>
                    {line.lot_name && (
                      <span>
                        {t("todo.replenishSheet.lot", { lot: line.lot_name })}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-sm text-on-secondary">
              {t("todo.replenishSheet.to", {
                location: proposal?.target_location_name ?? "",
              })}
            </p>
          </>
        )}
        {needsScan && lines.length > 0 && (
          <Input
            label={t("todo.replenishSheet.scan")}
            value={scannedCode}
            onChange={(event) => setScannedCode(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && scannedCode.trim()) submit();
            }}
          />
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={
              lines.length === 0 ||
              post.isPending ||
              (needsScan && !scannedCode.trim())
            }
          >
            {t("todo.replenishSheet.post")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
