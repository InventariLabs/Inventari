import { useCallback, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell, CheckCheck, Link2, Rocket } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import { formatDate } from "@/utils/helpers";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useConfirm } from "@/hooks/useConfirm";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import {
  useCampaignDetail,
  useSendReminders,
  useCompleteCampaign,
} from "@/modules/equipment/hooks/useEquipment";
import { useCampaignLaunch } from "@/modules/equipment/hooks/useCampaignLaunch";
import { CampaignParameters } from "@/modules/equipment/components/CampaignParameters";
import {
  campaignStatusLabel,
  completeMessage,
  disputeTypeLabel,
  responseDisplayStatus,
  responseStatusLabel,
} from "@/modules/equipment/components/campaignLabels";
import type { CampaignResponseRecord } from "@/modules/equipment/api/equipment";
import type { AuditResponseItemRecord } from "@/modules/equipment/api/equipment_campaigns";
import { announceReminderRun } from "@/modules/equipment/lib/campaignRuns";

// ---------------------------------------------------------------------------
// Response status badge
// ---------------------------------------------------------------------------

const RESPONSE_VARIANT: Record<
  string,
  "default" | "secondary" | "danger" | "outline"
> = {
  PENDING: "outline",
  CONFIRMED: "default",
  DISPUTED: "danger",
  EXPIRED: "secondary",
  RETURNED: "secondary",
};

function ResponseBadge({ status }: { status: string }) {
  const { t } = useTranslation("equipment");
  return (
    <Badge variant={RESPONSE_VARIANT[status] ?? "outline"}>
      {responseStatusLabel(t, status)}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Stats bar
// ---------------------------------------------------------------------------

function StatsBar({
  total,
  confirmed,
  disputed,
  pending,
  expired,
  returned = 0,
}: {
  total: number;
  confirmed: number;
  disputed: number;
  pending: number;
  expired: number;
  /** Unanswered, but every asset it asked about is back: closed, not pending. */
  returned?: number;
}) {
  const { t } = useTranslation("equipment");
  if (total === 0) return null;

  const pct = (n: number) => Math.round((n / total) * 100);

  return (
    <div className="space-y-2">
      <div className="flex h-3 rounded-full overflow-hidden bg-surface-raised">
        {confirmed > 0 && (
          <div
            className="bg-accent-500"
            style={{ width: `${pct(confirmed)}%` }}
            title={`Confirmed: ${confirmed}`}
          />
        )}
        {disputed > 0 && (
          <div
            className="bg-red-500"
            style={{ width: `${pct(disputed)}%` }}
            title={`Disputed: ${disputed}`}
          />
        )}
        {returned > 0 && (
          <div
            className="bg-on-muted/20"
            style={{ width: `${pct(returned)}%` }}
            title={`Returned: ${returned}`}
          />
        )}
        {expired > 0 && (
          <div
            className="bg-on-muted/40"
            style={{ width: `${pct(expired)}%` }}
            title={`Expired: ${expired}`}
          />
        )}
      </div>
      <div className="flex gap-4 text-xs text-on-secondary flex-wrap">
        <span>
          {t("attestation.stats.total", "Total")}: <b>{total}</b>
        </span>
        <span className="text-accent-400">
          {t("attestation.stats.confirmed", "Confirmed")}: <b>{confirmed}</b>
        </span>
        <span className="text-red-400">
          {t("attestation.stats.disputed", "Disputed")}: <b>{disputed}</b>
        </span>
        <span>
          {t("attestation.stats.pending", "Awaiting reply")}: <b>{pending}</b>
        </span>
        <span>
          {t("attestation.stats.expired", "Expired")}: <b>{expired}</b>
        </span>
        {returned > 0 && (
          <span>
            {t("attestation.stats.returned")}: <b>{returned}</b>
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// A link to hand over
// ---------------------------------------------------------------------------

/** Whether a response's link is the person's only way in: still unanswered,
 *  its assets still out, and no e-mail reached them — none was sent, or the
 *  organization sends none, so a reminder cannot reach them either. */
function needsHandingOver(
  r: CampaignResponseRecord,
  canSendEmail: boolean,
): boolean {
  return (
    r.status === "PENDING" &&
    !r.assets_returned &&
    (!r.email_sent_at || !canSendEmail)
  );
}

/**
 * Copies one person's attestation link, for a holder no e-mail reached.
 *
 * The New attestation dialog said requests "will have to be delivered by
 * hand" and no screen gave out the link to deliver.
 */
function CopyLinkButton({
  campaignId,
  responseId,
}: {
  campaignId: string;
  responseId: string;
}) {
  const { t } = useTranslation("equipment");
  const copy = async () => {
    try {
      const url = await equipmentApi.responseLink(campaignId, responseId);
      try {
        await navigator.clipboard.writeText(url);
        toast.success(t("attestation.linkCopied"));
      } catch {
        // No clipboard (an insecure origin, a denied permission): the link
        // is still the reader's, to copy by hand.
        toast.info(t("attestation.linkToCopy"), { description: url });
      }
    } catch (err) {
      toast.error(extractApiError(err, t("attestation.linkFailed")));
    }
  };
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => void copy()}
      leftIcon={<Link2 size={14} />}
    >
      {t("attestation.copyLink")}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Responses table
// ---------------------------------------------------------------------------

/** The asset a response row is about, as a way into its own page. */
function AssetLink({ item }: { item: AuditResponseItemRecord }) {
  if (!item.item_name) return <>{"\u2014"}</>;
  return (
    <Link to={`/equipment/${item.item_id}`} className="hover:underline">
      {item.item_name}
    </Link>
  );
}

function ResponsesTable({
  responses,
  campaignId,
  canHandOver,
  canSendEmail,
}: {
  responses: CampaignResponseRecord[];
  campaignId: string;
  /** Links can be given out: the reader may write and the campaign is live. */
  canHandOver: boolean;
  canSendEmail: boolean;
}) {
  const { t } = useTranslation("equipment");
  return (
    <>
      <div className="hidden md:block relative overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="pb-2 pr-4 text-xs font-medium text-on-muted">
                {t("attestation.response.assignee", "Assignee")}
              </th>
              {/* Surface the asset so reviewers can see which item each row is about. */}
              <th className="pb-2 pr-4 text-xs font-medium text-on-muted">
                {t("attestation.response.asset", "Asset")}
              </th>
              <th className="pb-2 pr-4 text-xs font-medium text-on-muted">
                {t("attestation.response.status", "Status")}
              </th>
              <th className="pb-2 pr-4 text-xs font-medium text-on-muted">
                {t("attestation.response.responded", "Responded")}
              </th>
              <th className="pb-2 text-xs font-medium text-on-muted">
                {t("attestation.response.note", "Note")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {responses.map((r) => (
              <tr key={r.id}>
                <td className="py-2 pr-4">
                  <div className="font-medium text-on">{r.assignee_name}</div>
                  <div className="text-on-muted text-xs">
                    {r.assignee_email}
                  </div>
                </td>
                <td className="py-2 pr-4">
                  {r.items.length > 0 ? (
                    <ul className="space-y-1">
                      {r.items.map((item) => (
                        <li key={item.id}>
                          <div className="font-medium text-on">
                            <AssetLink item={item} />
                            {item.returned && (
                              <span className="ml-1 text-xs font-normal text-on-muted">
                                ({t("attestation.public.itemReturned")})
                              </span>
                            )}
                            {r.items.length > 1 && !item.returned && (
                              <span className="ml-1 text-xs font-normal text-on-muted">
                                ({responseStatusLabel(t, item.status)})
                              </span>
                            )}
                          </div>
                          {item.serial_number && (
                            <div className="text-on-muted text-xs">
                              {t(
                                "attestation.public.serialNumber",
                                "Serial number",
                              )}
                              : {item.serial_number}
                            </div>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="font-medium text-on">
                      {r.item_name || "—"}
                    </div>
                  )}
                </td>
                <td className="py-2 pr-4">
                  <ResponseBadge status={responseDisplayStatus(r)} />
                  {canHandOver && needsHandingOver(r, canSendEmail) && (
                    <CopyLinkButton campaignId={campaignId} responseId={r.id} />
                  )}
                </td>
                <td className="py-2 pr-4 text-on-secondary text-sm">
                  {formatDate(r.responded_at)}
                </td>
                <td className="py-2 text-on-secondary text-xs">
                  <ResponseNote response={r} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ResponsesCards
        responses={responses}
        campaignId={campaignId}
        canHandOver={canHandOver}
        canSendEmail={canSendEmail}
      />
    </>
  );
}

/**
 * The same responses below `md`, one card each.
 *
 * The table stays the desktop list (§14.1); at 390px its five columns ran to
 * 470px and pushed the status marker, the response and the note past the right
 * edge, so the person running the attestation could not see the answer they
 * were there to read. A card branch keeps every field, in reading order, with
 * no horizontal scroll to discover.
 */
function ResponsesCards({
  responses,
  campaignId,
  canHandOver,
  canSendEmail,
}: {
  responses: CampaignResponseRecord[];
  campaignId: string;
  canHandOver: boolean;
  canSendEmail: boolean;
}) {
  const { t } = useTranslation("equipment");
  return (
    <ul className="md:hidden divide-y divide-border">
      {responses.map((r) => (
        <li key={r.id} className="py-3 space-y-1">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="font-medium text-on truncate">
                {r.assignee_name}
              </div>
              <div className="text-on-muted text-xs truncate">
                {r.assignee_email}
              </div>
            </div>
            <ResponseBadge status={responseDisplayStatus(r)} />
          </div>
          {canHandOver && needsHandingOver(r, canSendEmail) && (
            <CopyLinkButton campaignId={campaignId} responseId={r.id} />
          )}
          <div className="text-sm text-on">
            {r.items.length > 0 ? (
              <ul className="space-y-1">
                {r.items.map((item) => (
                  <li key={item.id} className="text-sm text-on">
                    <AssetLink item={item} />
                    {item.returned && (
                      <span className="text-on-muted text-xs">
                        {" "}
                        ({t("attestation.public.itemReturned")})
                      </span>
                    )}
                    {r.items.length > 1 && !item.returned && (
                      <span className="text-on-muted text-xs">
                        {" "}
                        ({responseStatusLabel(t, item.status)})
                      </span>
                    )}
                    {item.serial_number && (
                      <span className="text-on-muted text-xs">
                        {" "}
                        {t(
                          "attestation.public.serialNumber",
                          "Serial number",
                        )}: {item.serial_number}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <span>{r.item_name || "\u2014"}</span>
            )}
          </div>
          <div className="text-xs text-on-secondary">
            {formatDate(r.responded_at)}
          </div>
          <div className="text-xs text-on-secondary">
            <ResponseNote response={r} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * What the holder reported. With several assets each report names its own
 * asset; a response without reported items falls back to the envelope's note.
 */
function ResponseNote({ response }: { response: CampaignResponseRecord }) {
  const { t } = useTranslation("equipment");
  const reported = response.items.filter(
    (item) => item.status === "DISPUTED" && item.dispute_reason,
  );
  if (reported.length === 0) {
    return (
      <>
        {response.dispute_type && (
          <span className="text-red-400 mr-1">
            {disputeTypeLabel(t, response.dispute_type)}:
          </span>
        )}
        {response.dispute_reason ?? "—"}
      </>
    );
  }
  return (
    <ul className="space-y-1">
      {reported.map((item) => (
        <li key={item.id}>
          {item.item_name} —{" "}
          {item.dispute_type && (
            <span className="text-red-400">
              {disputeTypeLabel(t, item.dispute_type)}:
            </span>
          )}{" "}
          {item.dispute_reason}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Campaign Detail Page
// ---------------------------------------------------------------------------

export default function CampaignDetailPage() {
  const { t } = useTranslation("equipment");
  // The deadline is an org-clock day (pinned to the organization's zone on
  // write); `responded_at` below stays a reader moment.
  const formatOrgDay = useFormatOrgDay();
  const { id } = useParams<{ id: string }>();
  const {
    data: campaign,
    isLoading,
    isError,
    error,
    refetch,
  } = useCampaignDetail(id ?? "");
  // The booleans and the (stable) mutate functions are what the header
  // effect may depend on; the mutation result objects themselves are a new
  // reference every render and would re-run the effect forever.
  const { mutate: sendReminders, isPending: isSendingReminders } =
    useSendReminders();
  const { mutate: completeCampaign, isPending: isCompletingCampaign } =
    useCompleteCampaign();
  const { launch, launchingId, confirmDialogProps } = useCampaignLaunch();
  // Completing closes the campaign to every answer still out, so it asks
  // first — the list always did; this page closed it on the click.
  const { confirm, confirmDialogProps: completeDialogProps } = useConfirm();
  const completeAfterAsking = useCallback(
    async (campaignId: string, responses: CampaignResponseRecord[]) => {
      const ok = await confirm({
        title: t("attestation.confirm.completeTitle"),
        message: completeMessage(t, responses),
        confirmLabel: t("attestation.confirm.completeConfirm"),
      });
      if (ok) completeCampaign(campaignId);
    },
    [confirm, t, completeCampaign],
  );
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  const { data: organization } = useOrganization();
  const canSendEmail = organization?.can_send_email === true;

  useEffect(() => {
    if (!campaign) return;
    setHeader({
      title: campaign.name,
      subtitle: `${t("attestation.deadline", "Deadline")}: ${formatOrgDay(campaign.deadline)}`,
      backTo: "/equipment/campaigns",
      statusBadge: (
        <Badge variant={RESPONSE_VARIANT[campaign.status] ?? "outline"}>
          {campaignStatusLabel(t, campaign.status)}
        </Badge>
      ),
      actions: !canWrite ? undefined : campaign.status === "DRAFT" ? (
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
      ) : campaign.status === "ACTIVE" ? (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              sendReminders(campaign.id, {
                onSuccess: (run) => announceReminderRun(t, run),
              })
            }
            disabled={isSendingReminders}
          >
            <Bell size={14} className="mr-1" />
            {isSendingReminders
              ? t("attestation.sending", "Sending...")
              : t("attestation.sendReminders", "Send Reminders")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              void completeAfterAsking(campaign.id, campaign.responses)
            }
            disabled={isCompletingCampaign}
          >
            <CheckCheck size={14} className="mr-1" />
            {t("attestation.complete", "Complete")}
          </Button>
        </div>
      ) : undefined,
    });
    // The mutation *objects* must not enter the deps: React Query v5 hands
    // out a new result object every render, and an effect that re-runs on
    // every render re-sets the header forever. What it reads instead is the
    // pair that does belong here — the `isPending` booleans (fresh when the
    // request starts and ends) and the `mutate` functions (memoised by the
    // observer, so stable). `launch` is `useCallback`-stable for the same
    // reason: a click handler the header may hold across renders.
  }, [
    campaign,
    setHeader,
    t,
    launchingId,
    canWrite,
    launch,
    sendReminders,
    isSendingReminders,
    completeAfterAsking,
    isCompletingCampaign,
    formatOrgDay,
  ]);

  if (isLoading) return <LoadingSpinner />;
  if (isError && !isNotFoundError(error)) {
    return <QueryError onRetry={() => void refetch()} />;
  }
  if (!campaign) {
    return (
      <RecordNotFound
        title={t("attestation.notFound")}
        backTo="/equipment/campaigns"
        backLabel={t("attestation.backToList")}
      />
    );
  }

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="equipment" />
      <CampaignParameters
        scopeType={campaign.scope_type}
        scopeFilterId={campaign.scope_filter_id}
        deadline={campaign.deadline}
        reminderDaysBefore={campaign.reminder_days_before}
        emailSubject={campaign.email_subject}
      />

      {/* Stats */}
      <Card className="p-4 mb-4">
        <h2 className="text-sm font-semibold text-on mb-3">
          {t("attestation.progressTitle", "Response Progress")}
        </h2>
        <StatsBar {...campaign.stats} />
      </Card>

      {/* Responses */}
      <Card className="p-4">
        <h2 className="text-sm font-semibold text-on mb-3">
          {t("attestation.responsesTitle", "Individual Responses")} (
          {campaign.responses.length})
        </h2>
        {campaign.responses.length === 0 ? (
          <p className="text-sm text-on-secondary">
            {t(
              "attestation.noResponses",
              "No responses yet. Launch the campaign to generate links.",
            )}
          </p>
        ) : (
          <ResponsesTable
            responses={campaign.responses}
            campaignId={campaign.id}
            canHandOver={canWrite && campaign.status === "ACTIVE"}
            canSendEmail={canSendEmail}
          />
        )}
      </Card>

      <ConfirmDialog {...confirmDialogProps} />
      <ConfirmDialog {...completeDialogProps} />
    </div>
  );
}
