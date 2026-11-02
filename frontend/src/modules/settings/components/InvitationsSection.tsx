import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { UserPlus } from "lucide-react";
import { toast } from "sonner";
import { copyTextOrExplain } from "@/lib/clipboard";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { MEMBER_ROLES } from "@/modules/settings/memberRoles";
import {
  useCreateInvitationCode,
  useInvitations,
  useOrganization,
  useResendInvitation,
  useRevokeInvitation,
} from "@/modules/settings/hooks/useOrganization";
import { Badge } from "@/components/ui/Badge";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { useRoles } from "@/modules/settings/hooks/useRoles";
import type { Invitation, InvitationCode } from "@/lib/api/organizations";
import InvitationsList from "./InvitationsList";
import InviteLinkDialog from "./InviteLinkDialog";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const inviteLink = (code: string) =>
  `${window.location.origin}/join?code=${code}`;

/**
 * Invitations: who is being asked in, as what, and whether they arrived.
 *
 * The screen used to ask for a role and nothing else, hand back a link, and
 * show it in a panel that a page refresh took away. The list it kept was a
 * column of the word "User" with a status pushed to the far side of the
 * viewport — it could not name the invitee because the invitation had no
 * recipient to name.
 */
export default function InvitationsSection() {
  const { t } = useTranslation("common");
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState<string | null>(null);
  // The select's value is the enum level, or `custom:<role id>` for an
  // org-scoped custom role — one control carries both kinds.
  const [choice, setChoice] = useState<string>("user");
  const [issued, setIssued] = useState<{ email: string; link: string } | null>(
    null,
  );
  const [toRevoke, setToRevoke] = useState<Invitation | null>(null);

  const createInvite = useCreateInvitationCode();
  const resendInvite = useResendInvitation();
  const revokeInvite = useRevokeInvitation();
  const {
    data: invitations = [],
    isError: invitationsError,
    error: invitationsErrorValue,
    refetch: refetchInvitations,
  } = useInvitations();
  const { data: organization } = useOrganization();
  // This section renders for admins only (the inviter is always one), so the
  // roles query may run unconditionally here.
  const {
    data: rolesData,
    isError: rolesFailed,
    error: rolesError,
    refetch: refetchRoles,
  } = useRoles();
  const customRoles = (rolesData ?? []).filter((r) => !r.is_system);

  // Whether the organization can send at all decides what the button promises.
  // Read from the server rather than from the organization's own SMTP block:
  // an installation-wide mail server sends for organizations that have none
  // of their own, and reading the block would have the button offer a link
  // while the backend quietly posted the invitation instead.
  const canSend = organization?.can_send_email === true;

  // A custom role is named by whoever wrote it, so on the list its name sat
  // beside "Administrator" and "Member" with nothing saying it is not a
  // fourth built-in level. The picker separates the two with an optgroup;
  // the list says so with a badge.
  const roleLabel = (invitation: Invitation) => {
    if (invitation.role_id) {
      const custom = customRoles.find((r) => r.id === invitation.role_id);
      if (custom)
        return (
          <span className="inline-flex items-center gap-1.5">
            {custom.name}
            <Badge variant="secondary" className="text-[10px]">
              {t("settings.organization.memberRoleGroups.customBadge")}
            </Badge>
          </span>
        );
    }
    return t(`settings.organization.memberRoles.${invitation.role}`, {
      defaultValue: invitation.role,
    });
  };

  const copy = async (invitation: Invitation) => {
    if (
      await copyTextOrExplain(
        inviteLink(invitation.code),
        t("common:copy.failed"),
      )
    ) {
      toast.success(t("actions.copied"));
    }
  };

  // What the response can honestly say: the invitation is in the mail queue,
  // or it is not. "Sent" promised delivery the screen cannot observe — a
  // configured but dead SMTP still accepts the row, and the administrator was
  // told about a message that never left while the link they would have
  // needed stayed out of reach.
  const report = (address: string, data: InvitationCode) => {
    if (data.email_sent) {
      toast.success(
        t("settings.organization.inviteQueued", { email: address }),
      );
    } else {
      setIssued({ email: address, link: inviteLink(data.code) });
    }
  };

  const submit = () => {
    const address = email.trim();
    if (!address) {
      setEmailError(t("settings.organization.inviteEmailRequired"));
      return;
    }
    if (!EMAIL_PATTERN.test(address)) {
      setEmailError(t("settings.organization.inviteEmailInvalid"));
      return;
    }
    setEmailError(null);
    createInvite.mutate(
      choice.startsWith("custom:")
        ? { roleId: choice.slice(7), email: address }
        : { role: choice, email: address },
      {
        onSuccess: (data) => {
          setEmail("");
          report(address, data);
        },
      },
    );
  };

  const resend = (invitation: Invitation) => {
    resendInvite.mutate(invitation.id, {
      onSuccess: (data) => report(invitation.invited_email ?? "", data),
    });
  };

  return (
    <div className="px-4 py-3.5 space-y-4">
      <div className="flex items-center gap-2">
        <UserPlus size={15} className="text-on-muted shrink-0" />
        <p className="text-xs font-medium text-on-muted">
          {t("settings.organization.inviteTitle")}
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-end gap-2">
          <Input
            type="email"
            label={t("settings.organization.inviteEmail")}
            placeholder={t("settings.organization.inviteEmailPlaceholder")}
            wrapperClassName="flex-1 min-w-[14rem]"
            value={email}
            error={emailError ?? undefined}
            onChange={(e) => {
              setEmail(e.target.value);
              if (emailError) setEmailError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
          <NativeSelect
            label={t("settings.organization.inviteRole")}
            wrapperClassName="w-full sm:w-44"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          >
            <optgroup
              label={t("settings.organization.memberRoleGroups.builtin")}
            >
              {MEMBER_ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`settings.organization.memberRoles.${r}`)}
                </option>
              ))}
            </optgroup>
            {customRoles.length > 0 && (
              <optgroup
                label={t("settings.organization.memberRoleGroups.custom")}
              >
                {customRoles.map((r) => (
                  <option key={r.id} value={`custom:${r.id}`}>
                    {r.name}
                  </option>
                ))}
              </optgroup>
            )}
          </NativeSelect>
          {/* Without the roles the select offers the built-in ones only, and a
              custom role looks as if it did not exist. */}
          {rolesFailed && (
            <InlineQueryError
              error={rolesError}
              onRetry={() => void refetchRoles()}
            />
          )}
          <Button
            isLoading={createInvite.isPending}
            disabled={createInvite.isPending}
            onClick={submit}
          >
            {canSend
              ? t("settings.organization.sendInvite")
              : t("settings.organization.createInviteLink")}
          </Button>
        </div>

        <p className="text-xs text-on-muted">
          {t("settings.organization.inviteHint")}
        </p>

        {!canSend && (
          <p className="text-xs text-on-muted">
            {t("settings.organization.inviteNoSmtp")}{" "}
            <Link
              to="/settings/email"
              className="underline hover:text-on-secondary max-md:inline-block max-md:py-1.5"
            >
              {t("settings.organization.inviteNoSmtpLink")}
            </Link>
          </p>
        )}
      </div>

      {/* "No invitation has been issued yet" is a claim about the
          organization, and a failed request cannot make it. */}
      {invitationsError ? (
        <QueryFailure
          error={invitationsErrorValue}
          onRetry={() => refetchInvitations()}
        />
      ) : (
        <InvitationsList
          invitations={invitations}
          roleLabel={roleLabel}
          canResend={canSend}
          onCopy={(invitation) => void copy(invitation)}
          onResend={resend}
          onRevoke={setToRevoke}
        />
      )}

      {issued && (
        <InviteLinkDialog
          email={issued.email}
          link={issued.link}
          onClose={() => setIssued(null)}
        />
      )}

      <ConfirmDialog
        open={toRevoke !== null}
        title={t("settings.organization.revokeInvitationTitle")}
        message={t("settings.organization.revokeInvitationConfirm", {
          email: toRevoke?.invited_email ?? "",
        })}
        confirmLabel={t("settings.organization.revokeInvitation")}
        variant="danger"
        onConfirm={() => {
          if (toRevoke) {
            revokeInvite.mutate(toRevoke.id, {
              onSuccess: () =>
                toast.success(t("settings.organization.invitationRevoked")),
            });
          }
          setToRevoke(null);
        }}
        onCancel={() => setToRevoke(null)}
      />
    </div>
  );
}
