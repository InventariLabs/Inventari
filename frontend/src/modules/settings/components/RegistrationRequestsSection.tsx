import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { UserCheck, Copy, Check, X } from "lucide-react";
import { toast } from "sonner";
import { copyTextOrExplain } from "@/lib/clipboard";
import { formatDate } from "@/utils/formatters";
import Button from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineQueryError } from "@/components/ui/QueryResult";
import {
  useRegistrationRequests,
  useApproveRegistrationRequest,
  useRejectRegistrationRequest,
} from "@/modules/settings/hooks/useRegistrationRequests";

/**
 * Pending and approved-but-unfinished registration requests. Until this section existed the API
 * could approve a request but no screen could — the admin notification linked
 * to `/admin`, a global 404. Mounted admin-only inside OrganizationSettings;
 * renders nothing when there is nothing to approve, because an empty list
 * here would be a permanent fixture, not information. The one exception is a
 * link waiting to be handed over, which outlives the request it came from.
 */
export default function RegistrationRequestsSection() {
  const { t } = useTranslation("common");
  const { data: requests, isError, error, refetch } = useRegistrationRequests();
  const approveMutation = useApproveRegistrationRequest();
  const rejectMutation = useRejectRegistrationRequest();
  // The link SMTP could not deliver has to reach the user some other way.
  const [manualLink, setManualLink] = useState<string | null>(null);
  // Rejecting asks first, like revoking an invitation: it takes the person
  // out of the queue, and a mis-click next to Approve is easy.
  const [toReject, setToReject] = useState<{
    id: string;
    email: string;
  } | null>(null);

  // The admin notification links here (`/settings#registration-requests`):
  // the section sits far down the page, so landing at the top left the
  // request to be hunted for.
  // Hash-only navigation (the drawer link while already on Settings) changes
  // the location without remounting, and a repeat visit to the same hash
  // changes only the location key, so the effect follows the key.
  const { hash, key } = useLocation();
  const sectionRef = useRef<HTMLDivElement>(null);
  const pending = requests ?? [];
  const hasSection = pending.length > 0 || Boolean(manualLink) || isError;
  useEffect(() => {
    if (hash === "#registration-requests" && hasSection) {
      sectionRef.current?.scrollIntoView?.({ block: "center" });
    }
  }, [hasSection, hash, key]);
  // An approved request stays listed until the user registers, so a reload
  // cannot lose the link; a link just produced also survives the list
  // refetching without it.
  // A failed read keeps the section: hiding it would hide the requests too.
  if (!hasSection) return null;

  const handleApprove = (requestId: string) => {
    approveMutation.mutate(requestId, {
      onSuccess: (data) => {
        if (data.email_sent) {
          toast.success(t("settings.organization.requests.approved"));
        } else {
          setManualLink(`${window.location.origin}${data.registration_link}`);
        }
      },
    });
  };

  const copyLink = async () => {
    if (!manualLink) return;
    if (await copyTextOrExplain(manualLink, t("common:copy.failed"))) {
      toast.success(t("actions.copied"));
    }
  };

  return (
    <div
      id="registration-requests"
      ref={sectionRef}
      className="px-4 py-3.5 space-y-3"
    >
      <div className="flex items-center gap-2">
        <UserCheck size={15} className="text-on-muted shrink-0" />
        <p className="text-xs font-medium text-on-muted">
          {t("settings.organization.requests.title")}
        </p>
      </div>

      {isError && (
        <InlineQueryError error={error} onRetry={() => void refetch()} />
      )}

      <ul className="space-y-2">
        {pending.map((req) => (
          <li
            key={req.id}
            className="flex items-center gap-3 rounded-lg border border-border bg-surface-raised px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-on">
                {req.full_name || req.email}
              </p>
              {req.full_name && (
                <p className="truncate text-xs text-on-secondary">
                  {req.email}
                </p>
              )}
              <p className="text-xs text-on-secondary">
                {formatDate(req.created_at)}
              </p>
            </div>
            {req.accepted_at && (
              <span className="text-xs text-on-secondary">
                {t("settings.organization.requests.awaitingRegistration")}
              </span>
            )}
            <Button
              size="sm"
              onClick={() => handleApprove(req.id)}
              disabled={approveMutation.isPending || rejectMutation.isPending}
              aria-label={
                req.accepted_at
                  ? t("settings.organization.requests.newLinkFor", {
                      name: req.full_name || req.email,
                    })
                  : t("settings.organization.requests.approveFor", {
                      name: req.full_name || req.email,
                    })
              }
              leftIcon={<Check size={14} />}
            >
              {t(
                req.accepted_at
                  ? "settings.organization.requests.newLink"
                  : "settings.organization.requests.approve",
              )}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setToReject({ id: req.id, email: req.email })}
              disabled={approveMutation.isPending || rejectMutation.isPending}
              leftIcon={<X size={14} />}
              aria-label={t("settings.organization.requests.rejectFor", {
                name: req.full_name || req.email,
              })}
              className="text-on-secondary hover:text-red-600"
            >
              {t("settings.organization.requests.reject")}
            </Button>
          </li>
        ))}
      </ul>

      <ConfirmDialog
        open={toReject !== null}
        title={t("settings.organization.requests.rejectTitle")}
        message={t("settings.organization.requests.rejectConfirm", {
          email: toReject?.email ?? "",
        })}
        confirmLabel={t("settings.organization.requests.reject")}
        variant="danger"
        onConfirm={() => {
          if (toReject) {
            rejectMutation.mutate(toReject.id, {
              onSuccess: () =>
                toast.success(t("settings.organization.requests.rejected")),
            });
          }
          setToReject(null);
        }}
        onCancel={() => setToReject(null)}
      />

      {manualLink && (
        <div className="space-y-1.5">
          <p className="text-xs text-on-secondary">
            {t("settings.organization.requests.approvedNoEmail")}
          </p>
          <div className="flex items-center gap-2 p-3 bg-surface-raised rounded-lg border border-border">
            <p className="text-xs font-mono text-on-primary truncate flex-1">
              {manualLink}
            </p>
            <Button
              variant="ghost"
              size="iconSm"
              onClick={copyLink}
              className="shrink-0 text-on-muted hover:text-primary-600"
              aria-label={t("a11y.copyLink")}
            >
              <Copy size={14} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
