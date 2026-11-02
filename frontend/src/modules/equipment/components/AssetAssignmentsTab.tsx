import { useState } from "react";
import { useTranslation } from "react-i18next";
import { User, RotateCcw, FileText, MapPin } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import LoadingSpinner from "@/components/LoadingSpinner";
import {
  useItemAssignmentHistory,
  useDownloadProtocol,
} from "@/modules/equipment/hooks/useEquipment";
import {
  checkoutOfferable,
  getEquipmentMeta,
} from "@/modules/equipment/components/assetUtils";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import { formatDate } from "@/utils/helpers";
import type { Item } from "@/types";
import type { EquipmentAssignment } from "@/modules/equipment/api/equipment";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import { ProtocolPreviewDialog } from "@/modules/equipment/components/ProtocolPreviewDialog";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";

interface AssignmentsTabProps {
  item: Item;
  onCheckout: () => void;
  onCheckin: (assignment: EquipmentAssignment) => void;
  /** Check-out and check-in are writes; a reader gets neither. */
  canWrite?: boolean;
}

/** Who or what the card names first: the person, else the place, else the partner. */
function holderLine(a: EquipmentAssignment) {
  return (
    a.holder_name ??
    a.checkout_location_name ??
    a.partner_name ??
    a.assigned_to_name
  );
}

export function AssignmentsTab({
  item,
  onCheckout,
  onCheckin,
  canWrite = true,
}: AssignmentsTabProps) {
  const { t } = useTranslation("equipment");
  // The expected return is a day the backend pinned to the organization's
  // calendar; it owes the org's clock, not the reader's.
  const formatOrgDay = useFormatOrgDay();
  const {
    data: history = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useItemAssignmentHistory(item.id);
  const meta = getEquipmentMeta(item);
  // Checkout is offered to an asset nobody holds, whatever its (missing)
  // status; a held asset is offered its check-in, never a second hand-out.
  const offerCheckout = checkoutOfferable(meta.status);
  const downloadProtocol = useDownloadProtocol(t("protocol.download_failed"));
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewAssignmentId, setPreviewAssignmentId] = useState<string | null>(
    null,
  );

  const active = history.find((a: EquipmentAssignment) => !a.checked_in_at);

  const openProtocol = async (assignmentId: string) => {
    const { equipmentApi } = await import("@/modules/equipment/api/equipment");
    try {
      setPreviewAssignmentId(assignmentId);
      setPreviewHtml(await equipmentApi.fetchProtocolHtml(assignmentId));
    } catch (err) {
      setPreviewAssignmentId(null);
      // A refusal no longer vanishes into an unhandled rejection: the reader
      // gets the backend's own sentence.
      toast.error(
        extractApiError(err, t("protocol.preview_failed", "Preview failed")),
      );
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {/* Checkout and return need the live record; an archived one is
            refused both, so its card offers neither. */}
        {canWrite &&
          !item.is_deleted &&
          (offerCheckout && !active ? (
            <Button
              size="sm"
              leftIcon={<User size={16} />}
              onClick={onCheckout}
            >
              {t("assignments.checkout")}
            </Button>
          ) : active ? (
            <Button
              size="sm"
              variant="outline"
              leftIcon={<RotateCcw size={16} />}
              onClick={() => onCheckin(active)}
            >
              {t("assignments.checkin")}
            </Button>
          ) : null)}
      </div>

      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : history.length === 0 ? (
        <EmptyState variant="compact" title={t("assignments.no_active")} />
      ) : (
        <div className="space-y-2">
          {history.map((a: EquipmentAssignment) => (
            <Card key={a.id} className="p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-3">
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  {a.checkout_location_id ? (
                    <MapPin
                      size={16}
                      className="text-amber-500 flex-shrink-0"
                    />
                  ) : (
                    <User
                      size={16}
                      className="text-primary-500 flex-shrink-0"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="font-medium text-sm text-on">
                      {holderLine(a)}
                    </div>
                    {a.assigned_to_email && (
                      <div className="text-xs text-on-muted">
                        {a.assigned_to_email}
                      </div>
                    )}
                    {a.checkout_location_name &&
                      a.checkout_location_name !== holderLine(a) && (
                        <div className="text-xs text-on-muted">
                          {t(
                            "assignments.checkout_modal.select_location",
                            "Location",
                          )}
                          : {a.checkout_location_name}
                        </div>
                      )}
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-on-muted">
                      <span>
                        {t("assignments.checked_out_at")}:{" "}
                        {formatDate(a.checked_out_at)}
                      </span>
                      {a.expected_return_at && (
                        <span>
                          {t("assignments.expected_return")}:{" "}
                          {formatOrgDay(a.expected_return_at)}
                        </span>
                      )}
                      {a.checked_in_at && (
                        <span className="text-accent-600 dark:text-accent-400">
                          ↩ {formatDate(a.checked_in_at)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant={a.checked_in_at ? "secondary" : "info"}>
                    {a.checked_in_at
                      ? t("assignments.returned", "Returned")
                      : t("assignments.active", "Active")}
                  </Badge>
                  {a.checked_in_at && a.checkin_condition && (
                    <Badge
                      variant={
                        a.checkin_condition === "GOOD"
                          ? "success"
                          : a.checkin_condition === "DAMAGED"
                            ? "danger"
                            : "warning"
                      }
                    >
                      {t(
                        `assignments.condition_${a.checkin_condition.toLowerCase()}`,
                      )}
                    </Badge>
                  )}
                  {a.checked_in_at && a.checkin_notes && (
                    <span
                      className="text-xs text-on-muted max-w-[120px] truncate"
                      title={a.checkin_notes}
                    >
                      {a.checkin_notes}
                    </span>
                  )}
                </div>
                {/* The document, on every row and under its own name. Two
                    14px ghost icons used to stand here, and only while the
                    assignment was open -- so the return protocol, which the
                    backend renders from the CHECKIN template and an admin can
                    edit under Templates, had no way in at all. One control,
                    one label (UI_GUIDELINES 14.4): which of the two protocols
                    it is, the document's own title says. */}
                <div className="self-end sm:self-auto">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    leftIcon={<FileText size={16} />}
                    onClick={(e) => {
                      e.stopPropagation();
                      void openProtocol(a.id);
                    }}
                  >
                    {t("protocol.open")}
                  </Button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <ProtocolPreviewDialog
        html={previewHtml}
        onClose={() => {
          setPreviewHtml(null);
          setPreviewAssignmentId(null);
        }}
        onDownloadPdf={() => {
          if (previewAssignmentId) {
            downloadProtocol.mutate({ assignmentId: previewAssignmentId });
          }
        }}
        downloading={downloadProtocol.isPending}
      />
    </div>
  );
}
