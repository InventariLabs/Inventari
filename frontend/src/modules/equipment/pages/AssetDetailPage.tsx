import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { isNotFoundError } from "@/lib/errors";
import { AssetStatusBadge } from "@/modules/equipment/components/AssetStatusBadge";
import { AssetDetailHeaderActions } from "@/modules/equipment/components/AssetDetailHeaderActions";
import { CheckoutModal } from "@/modules/equipment/components/CheckoutModal";
import { CheckinModal } from "@/modules/equipment/components/CheckinModal";
import { MaintenanceLogModal } from "@/modules/equipment/components/MaintenanceLogModal";
import { queryKeys } from "@/hooks/queries/keys";
import { AssetTimeline } from "@/modules/equipment/components/AssetTimeline";
import { InfoTab } from "@/modules/equipment/components/AssetInfoTab";
import { AssignmentsTab } from "@/modules/equipment/components/AssetAssignmentsTab";
import { MaintenanceTab } from "@/modules/equipment/components/AssetMaintenanceTab";
import { AssetAttachmentsSection } from "@/modules/equipment/components/AssetAttachmentsSection";
import { useEquipmentAsset } from "@/modules/equipment/hooks/useEquipmentAssets";
import { useChangeAssetStatus } from "@/modules/equipment/hooks/useChangeAssetStatus";
import {
  useRetireEquipment,
  useArchiveEquipment,
  usePurgeEquipment,
  useRestoreEquipment,
  useItemAssignmentHistory,
  useDownloadProtocol,
} from "@/modules/equipment/hooks/useEquipment";
import { useApprovalStatus } from "@/modules/equipment/hooks/useMyAssets";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";
import type { EquipmentAssignment } from "@/modules/equipment/api/equipment";

type Tab = "timeline" | "info" | "assignments" | "maintenance";

export default function AssetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation("equipment");
  const queryClient = useQueryClient();

  const {
    data: item,
    isLoading,
    isError,
    error,
    refetch,
  } = useEquipmentAsset(id ?? "");
  const retireMutation = useRetireEquipment();
  const archiveMutation = useArchiveEquipment();
  const purgeMutation = usePurgeEquipment();
  const restoreMutation = useRestoreEquipment();
  const { changeStatus: handleChangeStatus, isPending: isBulkEditing } =
    useChangeAssetStatus(id);
  const { data: approvalStatus } = useApprovalStatus(id ?? "");
  const { data: assignments } = useItemAssignmentHistory(id ?? "");
  const activeAssignment = assignments?.find((a) => !a.checked_in_at) ?? null;

  const [showCheckout, setShowCheckout] = useState(false);
  // A request names the checkout it asks for, so it is asked from the same
  // dialog: the approver sees who gets the asset and until when.
  const [askForCheckout, setAskForCheckout] = useState(false);
  const [checkinTarget, setCheckinTarget] =
    useState<EquipmentAssignment | null>(null);
  const [showMaintenance, setShowMaintenance] = useState(false);

  const downloadProtocol = useDownloadProtocol(t("protocol.download_failed"));

  /**
   * The handover is over; the paper is offered, never forced.
   *
   * Printing on its own initiative is the wrong default: the application
   * cannot know whether a printer exists, and plenty of organizations want no
   * paper trail for a laptop at all. What was wrong was the opposite -- the
   * modal closed on silence and the document sat behind two unlabelled icons
   * on a tab nobody had reason to open. So the confirmation carries the offer,
   * and costs a reader who does not want it exactly nothing.
   */
  const offerTheProtocol = (assignment: EquipmentAssignment) => {
    // A place is not handed anything: the asset was put there.
    const done =
      assignment.holder_kind === "location"
        ? t("assignments.checkout_placed", {
            asset: item?.name ?? "",
            location: assignment.holder_name ?? "",
          })
        : t("assignments.checkout_done", { asset: item?.name ?? "" });
    toast.success(done, {
      action: {
        label: t("protocol.open"),
        onClick: () => downloadProtocol.mutate({ assignmentId: assignment.id }),
      },
    });
  };
  const [showRetireConfirm, setShowRetireConfirm] = useState(false);
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false);
  const [showPurgeConfirm, setShowPurgeConfirm] = useState(false);
  const [showRestoreConfirm, setShowRestoreConfirm] = useState(false);

  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  // retired (status) and archived (soft-deleted) are distinct —
  // restore/purge apply to archived assets only.
  const isArchived = Boolean(item?.is_deleted);

  useEffect(() => {
    if (!item) return;
    const m = getEquipmentMeta(item);
    setHeader({
      title: item.name,
      subtitle: item.brand ?? undefined,
      backTo: "/equipment",
      statusBadge: <AssetStatusBadge status={m.status} />,
      actions: canWrite ? (
        <AssetDetailHeaderActions
          itemId={item.id}
          status={m.status}
          isArchived={isArchived}
          activeAssignment={activeAssignment}
          approvalStatus={approvalStatus}
          onRequestApproval={() => setAskForCheckout(true)}
          onChangeStatus={handleChangeStatus}
          bulkEditPending={isBulkEditing}
          onCheckout={() => setShowCheckout(true)}
          onCheckin={(assignment) => setCheckinTarget(assignment)}
          onRestore={() => setShowRestoreConfirm(true)}
          onPurge={() => setShowPurgeConfirm(true)}
          onRetire={() => setShowRetireConfirm(true)}
          onArchive={() => setShowArchiveConfirm(true)}
        />
      ) : undefined,
    });
    // The mutation *object* must not enter these deps — React Query v5 hands
    // out a new result object every render, and an effect re-running on every
    // render re-sets the header forever. The `isPending` boolean and the
    // memoised `mutate` function do belong here, as does the
    // `useCallback`-wrapped status handler below.
  }, [
    item,
    setHeader,
    t,
    isArchived,
    approvalStatus,
    activeAssignment,
    canWrite,
    handleChangeStatus,
    isBulkEditing,
  ]);

  // Each of these is a confirm dialog's `onConfirm`, and each returns its
  // promise on purpose: the dialog then waits instead of closing on the click,
  // and a refused request keeps it open with the reason inside it. Closing on
  // failure left a screen identical to a successful one — the status
  // unchanged, the record where it was, and a toast already on its way out.
  const handleRetire = async () => {
    if (!id) return;
    await retireMutation.mutateAsync(id);
    // Retiring is a status change, not a removal: the asset is still here, and
    // the page the reader is on now shows it retired.
    toast.success(t("detail.retired"));
    setShowRetireConfirm(false);
  };

  const handleArchive = async () => {
    if (!id) return;
    await archiveMutation.mutateAsync(id);
    toast.success(t("detail.archived", "Asset archived"));
    navigate("/equipment");
  };

  const handlePurge = async () => {
    if (!id) return;
    await purgeMutation.mutateAsync({ itemId: id });
    toast.success(t("detail.purged"));
    navigate("/equipment");
  };

  const handleRestore = async () => {
    if (!id) return;
    await restoreMutation.mutateAsync(id);
    toast.success(t("detail.restored"));
    setShowRestoreConfirm(false);
  };

  if (isLoading) {
    return (
      <div>
        <LoadingSpinner />
      </div>
    );
  }

  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }

  if (!item) {
    return (
      <RecordNotFound
        title={t("detail.not_found")}
        backTo="/equipment"
        backLabel={t("list.back")}
      />
    );
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: "info", label: t("detail.tabs.info", "Info") },
    { key: "timeline", label: t("detail.tabs.timeline", "Timeline") },
    { key: "assignments", label: t("detail.tabs.assignments", "Assignments") },
    { key: "maintenance", label: t("detail.tabs.maintenance", "Maintenance") },
  ];

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="equipment" />
      <Tabs defaultValue="info">
        <TabsList className="w-full mb-5">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="info">
          <div className="space-y-4">
            <InfoTab
              item={item}
              activeAssignment={activeAssignment}
              onImageChanged={() => {
                queryClient.invalidateQueries({
                  queryKey: queryKeys.equipment.assets.detail(item.id),
                });
              }}
            />
            <AssetAttachmentsSection itemId={item.id} archived={isArchived} />
          </div>
        </TabsContent>
        <TabsContent value="timeline">
          <AssetTimeline item={item} />
        </TabsContent>
        <TabsContent value="assignments">
          <AssignmentsTab
            item={item}
            canWrite={canWrite}
            onCheckout={() => setShowCheckout(true)}
            onCheckin={(a) => setCheckinTarget(a)}
          />
        </TabsContent>
        <TabsContent value="maintenance">
          <MaintenanceTab
            item={item}
            canWrite={canWrite}
            onAdd={() => setShowMaintenance(true)}
            onEndService={() => handleChangeStatus("AVAILABLE")}
            endServicePending={isBulkEditing}
          />
        </TabsContent>
      </Tabs>

      {showCheckout && (
        <CheckoutModal
          item={item}
          onClose={() => setShowCheckout(false)}
          onDone={offerTheProtocol}
        />
      )}
      {askForCheckout && (
        <CheckoutModal
          item={item}
          purpose="request"
          onClose={() => setAskForCheckout(false)}
        />
      )}
      {checkinTarget && (
        <CheckinModal
          assignment={checkinTarget}
          homeLocationId={item.location_id}
          onClose={() => setCheckinTarget(null)}
        />
      )}
      {showMaintenance && (
        <MaintenanceLogModal
          itemId={item.id}
          itemName={item.name}
          status={getEquipmentMeta(item).status}
          onMarkInService={() => handleChangeStatus("MAINTENANCE")}
          onClose={() => setShowMaintenance(false)}
        />
      )}

      <ConfirmDialog
        open={showRetireConfirm}
        title={t("detail.confirm_retire")}
        message={t("detail.confirm_retire_msg")}
        confirmLabel={t("actions.retire")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="default"
        onConfirm={handleRetire}
        onCancel={() => setShowRetireConfirm(false)}
      />

      <ConfirmDialog
        open={showArchiveConfirm}
        title={t("detail.confirm_archive", "Archive asset?")}
        message={t("detail.confirm_archive_msg")}
        confirmLabel={t("actions.archive", "Archive")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="warning"
        onConfirm={handleArchive}
        onCancel={() => setShowArchiveConfirm(false)}
      />

      <ConfirmDialog
        open={showPurgeConfirm}
        title={t("detail.confirm_purge")}
        message={t("detail.confirm_purge_msg")}
        confirmLabel={t("actions.purge")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="danger"
        errorFallback={t("list.purge_failed")}
        onConfirm={handlePurge}
        onCancel={() => setShowPurgeConfirm(false)}
      />

      <ConfirmDialog
        open={showRestoreConfirm}
        title={t("actions.restore")}
        message={t("detail.confirm_restore_msg")}
        confirmLabel={t("actions.restore")}
        cancelLabel={t("common:actions.cancel", "Cancel")}
        variant="default"
        onConfirm={handleRestore}
        onCancel={() => setShowRestoreConfirm(false)}
      />
    </div>
  );
}
