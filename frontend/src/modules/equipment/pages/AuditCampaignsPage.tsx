import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Plus, Rocket, Eye, CheckCheck, Trash2, Ban } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useConfirm } from "@/hooks/useConfirm";
import { useCampaignLaunch } from "@/modules/equipment/hooks/useCampaignLaunch";
import {
  campaignStatusLabel,
  completeMessage,
} from "@/modules/equipment/components/campaignLabels";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import type { ScopeType } from "@/modules/equipment/api/equipment_campaigns";
import { usePagination } from "@/hooks/usePagination";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Badge } from "@/components/ui/Badge";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Pagination } from "@/module-sdk";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { formatDate } from "@/utils/helpers";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import {
  useCampaigns,
  useScopePreview,
  useCancelCampaign,
  useCompleteCampaign,
  useDeleteCampaign,
} from "@/modules/equipment/hooks/useEquipment";
import { CreateCampaignModal } from "@/modules/equipment/components/CreateCampaignModal";

// ---------------------------------------------------------------------------
// Status badge helper
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "danger" | "outline"
> = {
  DRAFT: "outline",
  ACTIVE: "default",
  COMPLETED: "secondary",
  CANCELLED: "danger",
};

// A draft names the people it will ask; past this many the rest is a count.
const AUDIENCE_NAMES_SHOWN = 5;

/**
 * Who a draft campaign will ask. The launch confirmation gave "people: 2"
 * and no names, so the audience stayed a number until the mail had gone.
 */
function DraftAudience({
  scopeType,
  scopeFilterId,
}: {
  scopeType: ScopeType;
  scopeFilterId: string | null;
}) {
  const { t } = useTranslation("equipment");
  const { data: preview } = useScopePreview(
    scopeType,
    scopeFilterId ?? undefined,
  );
  // No default list: a preview that failed to load says nothing here, rather
  // than reading as a campaign with nobody to ask (Launch still shows counts).
  const holders = preview?.holders;
  if (!holders || holders.length === 0) return null;
  const rest = holders.length - AUDIENCE_NAMES_SHOWN;
  const names =
    holders.slice(0, AUDIENCE_NAMES_SHOWN).join(", ") +
    (rest > 0 ? ` (+${rest})` : "");
  return (
    <p className="text-sm text-muted-foreground">
      {t("attestation.audience", { names })}
    </p>
  );
}

// Campaign cards are compact — bound the rendered DOM at 10 per page.
const CAMPAIGNS_PAGE_SIZE = 10;

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation("equipment");
  return (
    <Badge variant={STATUS_VARIANT[status] ?? "outline"}>
      {campaignStatusLabel(t, status)}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Main Page — Launch/Complete confirmations
// ---------------------------------------------------------------------------

export default function AuditCampaignsPage() {
  const { t } = useTranslation(["equipment", "common"]);
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  const { confirm, confirmDialogProps } = useConfirm();
  // The deadline is pinned to the organization's clock on write, so it is
  // read through that same clock; `launched_at` stays a reader moment.
  const formatOrgDay = useFormatOrgDay();
  const { data: campaigns = [], isLoading, isError, refetch } = useCampaigns();
  const {
    launch,
    launchingId,
    confirmDialogProps: launchDialogProps,
  } = useCampaignLaunch();
  const completeMutation = useCompleteCampaign();
  const cancelMutation = useCancelCampaign();
  const deleteMutation = useDeleteCampaign();
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");

  const filteredCampaigns = campaigns.filter(
    (c) => !search || c.name.toLowerCase().includes(search.toLowerCase()),
  );
  const pagination = usePagination(
    filteredCampaigns.length,
    CAMPAIGNS_PAGE_SIZE,
  );
  const visibleCampaigns = filteredCampaigns.slice(
    pagination.skip,
    pagination.skip + pagination.limit,
  );

  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            onClick={() => setShowCreate(true)}
            leftIcon={<Plus size={16} />}
          >
            {t("attestation.newCampaign", "New attestation")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  // Completing closes the campaign — confirm first.
  const handleComplete = async (campaignId: string) => {
    // The list carries no answers, so the campaign is fetched to count the
    // ones still out; a failed fetch asks the plain question.
    const detail = await equipmentApi.getCampaign(campaignId).catch(() => null);
    const ok = await confirm({
      title: t("attestation.confirm.completeTitle"),
      message: completeMessage(t, detail?.responses ?? null),
      confirmLabel: t("attestation.confirm.completeConfirm"),
    });
    if (!ok) return;
    completeMutation.mutate(campaignId);
  };

  // Not the same door as completing: a campaign called off did not finish,
  // and every link already in an inbox stops working the moment it is set.
  const handleCancel = async (campaignId: string) => {
    const ok = await confirm({
      title: t("attestation.confirm.cancelTitle"),
      message: t("attestation.confirm.cancelMessage"),
      confirmLabel: t("attestation.confirm.cancelConfirm"),
      variant: "danger",
    });
    if (!ok) return;
    cancelMutation.mutate(campaignId);
  };

  // Only a draft reaches this: nothing went out, so there is nothing to keep.
  const handleDelete = async (campaignId: string) => {
    const ok = await confirm({
      title: t("attestation.confirm.deleteTitle"),
      message: t("attestation.confirm.deleteMessage"),
      confirmLabel: t("common:actions.delete"),
      variant: "danger",
    });
    if (!ok) return;
    deleteMutation.mutate(campaignId);
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="equipment" />
      {showCreate && canWrite && (
        <CreateCampaignModal onClose={() => setShowCreate(false)} />
      )}

      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t(
            "attestation.searchPlaceholder",
            "Search campaigns...",
          ),
        }}
        resultCount={search ? filteredCampaigns.length : undefined}
      />

      {isError && <QueryError onRetry={() => refetch()} />}

      {!isError && isLoading && <LoadingSpinner />}

      {!isError && !isLoading && campaigns.length === 0 && (
        <EmptyState
          icon={CheckCheck}
          title={t("attestation.empty", "No attestations yet.")}
          description={
            // The how-to names an action only a writer can see; a viewer
            // pointed at a missing button is the action-without-path shape.
            canWrite
              ? t("attestation.emptyDescription")
              : t("attestation.emptyDescriptionViewer")
          }
        />
      )}

      <div className="space-y-3">
        {visibleCampaigns.map((campaign) => (
          <Card key={campaign.id} className="p-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <Link
                    to={`/equipment/campaigns/${campaign.id}`}
                    className="font-semibold hover:underline"
                  >
                    {campaign.name}
                  </Link>
                  <StatusBadge status={campaign.status} />
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {t("attestation.deadline", "Deadline")}:{" "}
                  {formatOrgDay(campaign.deadline)}
                  {campaign.launched_at &&
                    ` · ${t("attestation.launched", "Launched")}: ${formatDate(campaign.launched_at)}`}
                </p>
                {campaign.status === "DRAFT" && (
                  <DraftAudience
                    scopeType={campaign.scope_type}
                    scopeFilterId={campaign.scope_filter_id ?? null}
                  />
                )}
                {campaign.description && (
                  <p className="text-sm text-muted-foreground truncate">
                    {campaign.description}
                  </p>
                )}
              </div>

              <div className="flex flex-wrap gap-2 sm:shrink-0">
                {campaign.status === "DRAFT" && canWrite && (
                  <>
                    <Button
                      size="sm"
                      onClick={() => launch(campaign)}
                      disabled={launchingId === campaign.id}
                    >
                      <Rocket size={14} className="mr-1" />
                      {launchingId === campaign.id
                        ? t("attestation.launching", "Launching...")
                        : t("attestation.launch", "Launch")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghostDanger"
                      onClick={() => handleDelete(campaign.id)}
                      disabled={deleteMutation.isPending}
                      aria-label={t("common:actions.delete")}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </>
                )}
                {campaign.status === "ACTIVE" && (
                  <>
                    <Link to={`/equipment/campaigns/${campaign.id}`}>
                      <Button size="sm" variant="outline">
                        <Eye size={14} className="mr-1" />
                        {t("attestation.viewDetail", "Details")}
                      </Button>
                    </Link>
                    {canWrite && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleComplete(campaign.id)}
                          disabled={completeMutation.isPending}
                        >
                          <CheckCheck size={14} className="mr-1" />
                          {t("attestation.complete", "Complete")}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghostDanger"
                          onClick={() => handleCancel(campaign.id)}
                          disabled={cancelMutation.isPending}
                          aria-label={t("attestation.cancel")}
                        >
                          <Ban size={14} />
                        </Button>
                      </>
                    )}
                  </>
                )}
                {/* Anything closed — completed or called off — is still there
                    to be read, which is the reason cancelling exists. */}
                {(campaign.status === "COMPLETED" ||
                  campaign.status === "CANCELLED") && (
                  <Link to={`/equipment/campaigns/${campaign.id}`}>
                    <Button size="sm" variant="ghost">
                      {t("attestation.viewDetail", "Details")}
                    </Button>
                  </Link>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      {filteredCampaigns.length > CAMPAIGNS_PAGE_SIZE && (
        <Pagination
          skip={pagination.skip}
          limit={pagination.limit}
          total={filteredCampaigns.length}
          onPrev={pagination.onPrev}
          onNext={pagination.onNext}
        />
      )}

      <ConfirmDialog {...confirmDialogProps} />
      <ConfirmDialog {...launchDialogProps} />
    </div>
  );
}
