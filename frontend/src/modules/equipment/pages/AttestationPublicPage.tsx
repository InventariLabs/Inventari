/**
 * Public attestation page — zero-login asset confirm/dispute flow.
 * Accessible at /public/attestation/:token without authentication.
 *
 * Surfaces asset name + serial number and is fully translated
 * via the ``attestation.public`` namespace. The language is chosen from
 * the ``?lang=`` query parameter (so email links can pin a language) and
 * falls back to the i18next detector (localStorage / navigator).
 */

import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import i18next from "i18next";
import axios from "axios";
import { XCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import LoadingSpinner from "@/components/LoadingSpinner";
import { SUPPORTED_LANGUAGES, type Language } from "@/i18n/languages";
import { StatusDisplay } from "@/modules/equipment/components/attestation/StatusDisplay";
import { AnswerButtons } from "@/modules/equipment/components/attestation/AnswerButtons";
import { DisputeForm } from "@/modules/equipment/components/attestation/DisputeForm";
import { queryKeys } from "@/hooks/queries/keys";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { apiErrorStatus, extractApiError } from "@/lib/errors";
import type { AuditResponseRecord } from "@/modules/equipment/api/equipment";

// ---------------------------------------------------------------------------
// Unauthenticated API helpers (no /api/v1 prefix needed for public endpoint)
// ---------------------------------------------------------------------------

const publicApi = axios.create({ baseURL: "/" });

// The reader picked this page's language with the ?lang= parameter (the
// email link chose it), not with a browser setting — and the API's own
// refusals (an expired link, a spent token) surface here verbatim through
// useAppMutation. So the public calls must carry the chosen language the
// way the authenticated client does; read at request time, because this
// module imports before i18n is initialized.
publicApi.interceptors.request.use((config) => {
  config.headers["Accept-Language"] = i18next.language || "en";
  return config;
});

async function getAttestationResponse(
  token: string,
): Promise<AuditResponseRecord> {
  const r = await publicApi.get<AuditResponseRecord>(
    `/public/attestation/${token}`,
  );
  return r.data;
}

async function confirmAttestation(token: string): Promise<AuditResponseRecord> {
  const r = await publicApi.post<AuditResponseRecord>(
    `/public/attestation/${token}/confirm`,
  );
  return r.data;
}

async function disputeAttestation(
  token: string,
  disputeType: string,
  reason: string,
  assignmentId?: string,
): Promise<AuditResponseRecord> {
  const r = await publicApi.post<AuditResponseRecord>(
    `/public/attestation/${token}/dispute`,
    {
      dispute_type: disputeType,
      reason,
      assignment_id: assignmentId,
    },
  );
  return r.data;
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

/**
 * The request failed, the link may be fine: say so and let the reader ask
 * again rather than calling a live link dead.
 */
function LoadFailedCard({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useTranslation("equipment");
  const loadFailedDesc = t("attestation.public.loadFailedDesc");
  // A 429 is the server pausing this visitor, and its own sentence, in the
  // language the page asked for, says so.
  const description =
    apiErrorStatus(error) === 429
      ? extractApiError(error, loadFailedDesc)
      : loadFailedDesc;
  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <Card className="w-full max-w-md p-8 text-center">
        <XCircle size={48} className="mx-auto mb-4 text-on-muted" />
        {/* eslint-disable-next-line no-restricted-syntax -- standalone public page outside ModuleShell: <h1> is the document title of the attestation link, not a shell page heading */}
        <h1 className="text-xl font-semibold text-on mb-2">
          {t("attestation.public.loadFailed")}
        </h1>
        <p className="text-on-secondary mb-4">{description}</p>
        <Button onClick={onRetry}>{t("common:actions.retry")}</Button>
      </Card>
    </div>
  );
}

/**
 * Where one asset of the request stands: back with the organization already
 * (the confirmation covers only what the person still has), or answered by an
 * earlier visit.
 */
function ItemState({ item }: { item: AuditResponseRecord["items"][number] }) {
  const { t } = useTranslation("equipment");
  let state: string | null = null;
  if (item.returned) state = t("attestation.public.itemReturned");
  else if (item.status === "DISPUTED")
    state = t("attestation.public.itemReported");
  else if (item.status === "CONFIRMED")
    state = t("attestation.public.itemConfirmed");
  if (!state) return null;
  return <span className="text-sm text-on-secondary"> — {state}</span>;
}

/** Still to be answered: out with the person and not yet confirmed or reported. */
function isOpen(item: AuditResponseRecord["items"][number]): boolean {
  return !item.returned && item.status === "PENDING";
}

/**
 * What the page asks of the reader. A report on one asset leaves the others to
 * answer, and says so instead of repeating the first-visit instructions.
 */
function Instructions({ items }: { items: AuditResponseRecord["items"] }) {
  const { t } = useTranslation("equipment");
  return (
    <p className="text-sm text-on-secondary mb-6">
      {items.some((item) => item.status === "DISPUTED")
        ? t("attestation.public.reportedStillOpen")
        : t("attestation.public.instructions")}
    </p>
  );
}

export default function AttestationPublicPage() {
  const { t, i18n } = useTranslation("equipment");
  const { token } = useParams<{ token: string }>();
  const [searchParams] = useSearchParams();
  const [showDispute, setShowDispute] = useState(false);
  const [currentResponse, setCurrentResponse] =
    useState<AuditResponseRecord | null>(null);

  // Pin the i18n language from ?lang=xx so email links can target a language
  // regardless of the browser default. The change is a no-op when the param
  // is missing or unsupported.
  const langParam = searchParams.get("lang");
  useEffect(() => {
    if (!langParam) return;
    const normalised = langParam.toLowerCase().split("-")[0];
    if (SUPPORTED_LANGUAGES.includes(normalised as Language)) {
      if (i18n.language !== normalised) {
        void i18n.changeLanguage(normalised);
      }
    }
  }, [langParam, i18n]);

  const {
    data: response,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.attestation.response(token),
    queryFn: () => getAttestationResponse(token ?? ""),
    enabled: Boolean(token),
    retry: false,
  });

  // Nothing to invalidate — the answer lands in local state below and the
  // token-scoped query is never refetched. What matters here is the failure
  // path: this page is public, so a failed confirm must say so on screen,
  // which is exactly what useAppMutation adds over a bare useMutation.
  const confirmMutation = useAppMutation(
    () => confirmAttestation(token ?? ""),
    () => {},
    { errorFallback: t("attestation.public.actionFailed") },
  );

  const disputeMutation = useAppMutation(
    ({
      disputeType,
      reason,
      assignmentId,
    }: {
      disputeType: string;
      reason: string;
      assignmentId?: string;
    }) => disputeAttestation(token ?? "", disputeType, reason, assignmentId),
    () => {},
    { errorFallback: t("attestation.public.actionFailed") },
  );

  const displayResponse = currentResponse ?? response;

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  const failureStatus = error ? apiErrorStatus(error) : null;
  // A 429 is the server pausing this visitor, not a verdict on the token.
  const rateLimited = failureStatus === 429;
  const linkIsDead =
    failureStatus !== null &&
    failureStatus >= 400 &&
    failureStatus < 500 &&
    !rateLimited;
  if (error && !linkIsDead && !displayResponse) {
    return <LoadFailedCard error={error} onRetry={() => void refetch()} />;
  }

  if (error || !displayResponse) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="w-full max-w-md p-8 text-center">
          <XCircle size={48} className="mx-auto mb-4 text-on-muted" />
          {/* eslint-disable-next-line no-restricted-syntax -- standalone public page outside ModuleShell: <h1> is the document title of the attestation link, not a shell page heading */}
          <h1 className="text-xl font-semibold text-on mb-2">
            {t("attestation.public.linkNotFound")}
          </h1>
          <p className="text-on-secondary">
            {t("attestation.public.linkNotFoundDesc")}
          </p>
          {/* A dead end otherwise: the reader has no account here, so there
              is nothing to navigate to — what they need is who to ask. */}
          <p className="mt-3 text-sm text-on-muted">
            {t("attestation.public.linkNotFoundNext")}
          </p>
        </Card>
      </div>
    );
  }

  const isResolved =
    displayResponse.status === "CONFIRMED" ||
    displayResponse.status === "DISPUTED" ||
    displayResponse.status === "EXPIRED";

  // Why the link can no longer take an answer, when the server already
  // knows: the equipment went back, the campaign closed, the token aged
  // out. The page says it instead of offering buttons whose only outcome
  // is a refusal — an answer already given still wins (see StatusDisplay).
  const closedReason = displayResponse.closed_reason ?? null;

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-4">
      <Card className="w-full max-w-md p-8">
        {/* Header */}
        <div className="text-center mb-6">
          {/* eslint-disable-next-line no-restricted-syntax -- standalone public page outside ModuleShell: <h1> is the document title of the attestation link, not a shell page heading */}
          <h1 className="text-2xl font-semibold text-on">
            {t("attestation.public.pageTitle")}
          </h1>
          <p className="text-on-muted text-sm mt-1">
            {t("attestation.public.brand")}
          </p>
        </div>

        {/* Resolved or closed state */}
        {(isResolved || closedReason) && (
          <StatusDisplay
            status={displayResponse.status}
            closedReason={closedReason}
          />
        )}

        {/* Pending state */}
        {!isResolved && !closedReason && (
          <>
            {/* Asset section so the attester knows what they are confirming. */}
            <div className="bg-surface-raised rounded-lg p-4 mb-3 space-y-2">
              <p className="text-sm text-on-muted">
                {displayResponse.items.length > 1
                  ? t("attestation.public.itemsSection")
                  : t("attestation.public.assetSection")}
              </p>
              {displayResponse.items.length > 0 ? (
                <ul className="space-y-1.5">
                  {displayResponse.items.map((item) => (
                    <li key={item.id} className="text-on">
                      <span className="font-semibold break-words">
                        {item.item_name || "—"}
                      </span>
                      {item.serial_number && (
                        <span className="text-sm text-on-secondary">
                          {" "}
                          ({item.serial_number})
                        </span>
                      )}
                      <ItemState item={item} />
                    </li>
                  ))}
                </ul>
              ) : (
                <>
                  <p className="font-semibold text-on break-words">
                    {displayResponse.item_name || "—"}
                  </p>
                  {displayResponse.serial_number && (
                    <p className="text-sm text-on-secondary">
                      {t("attestation.public.serialNumber")}:{" "}
                      {displayResponse.serial_number}
                    </p>
                  )}
                </>
              )}
            </div>

            <div className="bg-surface-raised rounded-lg p-4 mb-6 space-y-1">
              <p className="text-sm text-on-muted">
                {t("attestation.public.assignedTo")}
              </p>
              <p className="font-semibold text-on">
                {displayResponse.assignee_name}
              </p>
              <p className="text-sm text-on-secondary">
                {displayResponse.assignee_email}
              </p>
            </div>

            <Instructions items={displayResponse.items} />

            {!showDispute && (
              <AnswerButtons
                onConfirm={() =>
                  confirmMutation.mutate(undefined, {
                    onSuccess: (data) => setCurrentResponse(data),
                  })
                }
                onReport={() => setShowDispute(true)}
                isPending={confirmMutation.isPending}
              />
            )}

            {showDispute && (
              <DisputeForm
                items={displayResponse.items.filter(isOpen)}
                onSubmit={(type, reason, assignmentId) =>
                  disputeMutation.mutate(
                    {
                      disputeType: type,
                      reason,
                      assignmentId,
                    },
                    {
                      onSuccess: (data) => {
                        setCurrentResponse(data);
                        setShowDispute(false);
                      },
                    },
                  )
                }
                onCancel={() => setShowDispute(false)}
                isPending={disputeMutation.isPending}
              />
            )}
          </>
        )}

        {/* Footer */}
        <p className="text-xs text-on-muted text-center mt-6">
          {t("attestation.public.footer")}
        </p>
      </Card>
    </div>
  );
}
