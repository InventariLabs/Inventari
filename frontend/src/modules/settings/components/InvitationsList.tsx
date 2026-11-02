import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Copy, Mail, MailPlus, Trash2 } from "lucide-react";
import { ActionMenu } from "@/components/ui/ActionMenu";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatDateMedium } from "@/utils/formatters";
import type { Invitation } from "@/lib/api/organizations";

type InvitationState = "PENDING" | "USED" | "EXPIRED" | "NOT_DELIVERED";

/**
 * Redeemed and expired outrank a lost mail, in that order.
 *
 * A code that was used arrived by some route, whatever the queue says; an
 * expired one cannot be acted on either way. What is left is the case the
 * list could not show at all: live, unredeemed, and the message carrying it
 * never got there — which reads exactly like one waiting in an inbox while
 * asking the opposite thing of an administrator.
 */
function invitationState(invitation: Invitation): InvitationState {
  if (invitation.is_used) return "USED";
  if (new Date(invitation.expires_at).getTime() < Date.now()) return "EXPIRED";
  return invitation.email_status === "failed" ? "NOT_DELIVERED" : "PENDING";
}

interface InvitationsListProps {
  invitations: Invitation[];
  roleLabel: (invitation: Invitation) => ReactNode;
  /** Resending puts mail in someone's inbox, so it needs a mail server. */
  canResend: boolean;
  onCopy: (invitation: Invitation) => void;
  onResend: (invitation: Invitation) => void;
  onRevoke: (invitation: Invitation) => void;
}

/**
 * Who has been invited, as what, and whether they arrived.
 *
 * The old list led with the role, which every row shared, and pushed the
 * status to the far edge of the viewport in one of two greys. The recipient
 * is what makes a row one row and not another, so it comes first; the status
 * carries shape and colour together and stays beside what it describes.
 *
 * Expired invitations start folded away. They are the majority in any
 * organization that has been inviting people for a while, and none of them
 * can be acted on.
 */
export default function InvitationsList({
  invitations,
  roleLabel,
  canResend,
  onCopy,
  onResend,
  onRevoke,
}: InvitationsListProps) {
  const { t } = useTranslation("common");
  const [showExpired, setShowExpired] = useState(false);

  const { live, expired } = useMemo(() => {
    const expiredRows = invitations.filter(
      (i) => invitationState(i) === "EXPIRED",
    );
    return {
      live: invitations.filter((i) => invitationState(i) !== "EXPIRED"),
      expired: expiredRows,
    };
  }, [invitations]);

  const visible = showExpired ? [...live, ...expired] : live;
  const pending = live.filter((i) => invitationState(i) === "PENDING").length;

  if (invitations.length === 0) {
    return (
      <EmptyState
        variant="compact"
        icon={Mail}
        title={t("settings.organization.noInvitations")}
        description={t("settings.organization.noInvitationsHint")}
      />
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-xs font-medium text-on-muted">
          {t("settings.organization.invitationsTitle")}
          {pending > 0 && (
            <span className="text-on-secondary">
              {" · "}
              {t("settings.organization.invitationsPending", { n: pending })}
            </span>
          )}
        </p>
        {expired.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="text-xs text-on-muted"
            onClick={() => setShowExpired((shown) => !shown)}
          >
            {showExpired
              ? t("settings.organization.hideExpired")
              : t("settings.organization.showExpired", {
                  n: expired.length,
                })}
          </Button>
        )}
      </div>

      {visible.length === 0 ? (
        <p className="text-xs text-on-muted py-2">
          {t("settings.organization.noLiveInvitations")}
        </p>
      ) : (
        <>
          <InvitationCards
            invitations={visible}
            roleLabel={roleLabel}
            canResend={canResend}
            onCopy={onCopy}
            onResend={onResend}
            onRevoke={onRevoke}
          />
          <InvitationTable
            invitations={visible}
            roleLabel={roleLabel}
            canResend={canResend}
            onCopy={onCopy}
            onResend={onResend}
            onRevoke={onRevoke}
          />
        </>
      )}
    </div>
  );
}

const STATUS_VARIANTS = {
  PENDING: "warning",
  USED: "success",
  EXPIRED: "secondary",
  NOT_DELIVERED: "danger",
} as const;

function InvitationStatus({ invitation }: { invitation: Invitation }) {
  const { t } = useTranslation("common");
  const state = invitationState(invitation);
  const labels: Record<InvitationState, string> = {
    PENDING: t("settings.organization.invitationWaiting"),
    USED: t("settings.organization.invitationUsed"),
    EXPIRED: t("settings.organization.invitationExpired"),
    NOT_DELIVERED: t("settings.organization.invitationNotDelivered"),
  };
  return (
    <StatusBadge
      status={state}
      variants={STATUS_VARIANTS}
      label={labels[state]}
    />
  );
}

/** The address, and — once redeemed — when the account walked through. */
function InvitationRecipient({ invitation }: { invitation: Invitation }) {
  const { t } = useTranslation("common");
  return (
    <>
      <span className="text-sm text-on truncate block">
        {invitation.invited_email ?? (
          <span className="text-on-muted italic">
            {t("settings.organization.invitationNoRecipient")}
          </span>
        )}
      </span>
      {invitation.used_at && (
        <span className="text-xs text-on-muted truncate block">
          {t("settings.organization.invitationJoined", {
            time: formatDateMedium(invitation.used_at),
          })}
        </span>
      )}
    </>
  );
}

function useRowActions({
  invitation,
  canResend,
  onCopy,
  onResend,
  onRevoke,
}: {
  invitation: Invitation;
  canResend: boolean;
  onCopy: (invitation: Invitation) => void;
  onResend: (invitation: Invitation) => void;
  onRevoke: (invitation: Invitation) => void;
}) {
  const { t } = useTranslation("common");
  const pending = invitationState(invitation) === "PENDING";
  return [
    {
      id: "copy",
      label: t("settings.organization.copyInviteLink"),
      icon: <Copy size={14} />,
      disabled: !pending,
      onSelect: () => onCopy(invitation),
    },
    {
      id: "resend",
      label: t("settings.organization.resendInvitation"),
      icon: <MailPlus size={14} />,
      disabled: !canResend || invitation.is_used || !invitation.invited_email,
      onSelect: () => onResend(invitation),
    },
    {
      id: "revoke",
      label: t("settings.organization.revokeInvitation"),
      icon: <Trash2 size={14} />,
      disabled: invitation.is_used,
      destructive: true,
      onSelect: () => onRevoke(invitation),
    },
  ];
}

function InvitationRowMenu(props: {
  invitation: Invitation;
  canResend: boolean;
  onCopy: (invitation: Invitation) => void;
  onResend: (invitation: Invitation) => void;
  onRevoke: (invitation: Invitation) => void;
}) {
  const { t } = useTranslation("common");
  const actions = useRowActions(props);
  return (
    <ActionMenu
      actions={actions}
      label={t("settings.organization.invitationActions", {
        email:
          props.invitation.invited_email ??
          t("settings.organization.invitationNoRecipient"),
      })}
    />
  );
}

function InvitationTable({
  invitations,
  roleLabel,
  canResend,
  onCopy,
  onResend,
  onRevoke,
}: InvitationsListProps) {
  const { t } = useTranslation("common");
  // Spelled out rather than built from a template literal: the i18n gate reads
  // call sites, and a key it cannot see is a key it reports as dead.
  const columns = [
    t("settings.organization.invitationColumns.recipient"),
    t("settings.organization.invitationColumns.role"),
    t("settings.organization.invitationColumns.expires"),
    t("settings.organization.invitationColumns.status"),
  ];
  return (
    <div className="relative hidden sm:block overflow-x-auto">
      {/* Percentages rather than `fr`: a table has no grid track sizing, and
          `table-fixed` scales the columns the same way (§14.1). */}
      <table
        data-testid="invitations-table"
        className="w-full table-fixed text-sm"
      >
        <colgroup>
          <col className="w-[38%]" />
          <col className="w-[20%]" />
          <col className="w-[18%]" />
          <col className="w-[16%]" />
          <col className="w-[8%]" />
        </colgroup>
        <thead>
          <tr className="border-b border-border">
            {columns.map((column) => (
              <th
                key={column}
                scope="col"
                className="px-2 py-2 text-left text-xs font-medium uppercase tracking-wide text-on-secondary"
              >
                {column}
              </th>
            ))}
            <th scope="col" className="px-2 py-2 text-right">
              <span className="sr-only">
                {t("settings.organization.invitationColumns.actions")}
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {invitations.map((invitation) => (
            <tr
              key={invitation.id}
              data-testid="invitation-row"
              className="border-b border-border last:border-0 hover:bg-surface-raised"
            >
              <td className="px-2 py-2 min-w-0">
                <InvitationRecipient invitation={invitation} />
              </td>
              <td className="px-2 py-2 text-on-secondary truncate">
                {roleLabel(invitation)}
              </td>
              <td className="px-2 py-2 text-on-secondary tabular-nums">
                {formatDateMedium(invitation.expires_at)}
              </td>
              <td className="px-2 py-2">
                <InvitationStatus invitation={invitation} />
              </td>
              <td className="px-2 py-2 text-right">
                <InvitationRowMenu
                  invitation={invitation}
                  canResend={canResend}
                  onCopy={onCopy}
                  onResend={onResend}
                  onRevoke={onRevoke}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvitationCards({
  invitations,
  roleLabel,
  canResend,
  onCopy,
  onResend,
  onRevoke,
}: InvitationsListProps) {
  const { t } = useTranslation("common");
  return (
    <div
      data-testid="invitations-cards"
      className="flex flex-col gap-2 sm:hidden"
    >
      {invitations.map((invitation) => (
        <div
          key={invitation.id}
          data-testid="invitation-row"
          className="rounded-lg border border-border p-3 space-y-2"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <InvitationRecipient invitation={invitation} />
            </div>
            <InvitationRowMenu
              invitation={invitation}
              canResend={canResend}
              onCopy={onCopy}
              onResend={onResend}
              onRevoke={onRevoke}
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-on-secondary truncate">
              {roleLabel(invitation)}
              {" · "}
              {t("settings.organization.invitationExpiresAt", {
                time: formatDateMedium(invitation.expires_at),
              })}
            </span>
            <InvitationStatus invitation={invitation} />
          </div>
        </div>
      ))}
    </div>
  );
}
