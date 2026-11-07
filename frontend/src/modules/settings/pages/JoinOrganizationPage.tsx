import { useEffect, useRef, useState } from "react";
import { logger } from "@/utils/logger";
import {
  useSearchParams,
  useParams,
  useNavigate,
  Navigate,
} from "react-router-dom";
import {
  useJoinOrganization,
  useInvitationCheck,
  useOrganization,
} from "@/modules/settings/hooks/useOrganization";
import { useAuthStore } from "@/store/authStore";
import { toast } from "sonner";
import {
  extractApiError,
  extractApiErrorCode,
  apiErrorStatus,
} from "@/lib/errors";
import { Loader2, Home, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";

/**
 * What a dead join link looks like: the link is named as the problem, and
 * the person who can issue a fresh one is named with it — the same shape
 * the public attestation page answers a dead link with. No button: a
 * signed-out reader has no account to navigate anywhere with (registering
 * from here is exactly the own-organization trap the message exists to
 * prevent), and a signed-in reader has already been told the link is at
 * fault.
 */
function LinkNotFoundCard() {
  const { t } = useTranslation("common");
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="bg-surface-card p-8 rounded-3xl shadow-md max-w-md w-full text-center">
        <XCircle size={48} className="mx-auto mb-4 text-on-muted" />
        <h2 className="text-2xl font-semibold text-on mb-2">
          {t("settings.organization.linkNotFound")}
        </h2>
        <p className="text-on-secondary mb-6">
          {t("settings.organization.linkNotFoundDesc")}
        </p>
        <p className="text-sm text-on-muted">
          {t("settings.organization.linkNotFoundNext")}
        </p>
      </div>
    </div>
  );
}

/**
 * A live link opened while signed in as another account: the invitation was
 * written for a different address. The reader is not told the link is dead —
 * it is not — but that they are signed in as the wrong person, with the way
 * out in reach. Signing out leaves them on this very link, signed out, where
 * registration with the code attached is the door.
 */
function WrongAccountCard() {
  const { t } = useTranslation("common");
  const logout = useAuthStore((state) => state.logout);
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="bg-surface-card p-8 rounded-3xl shadow-md max-w-md w-full text-center">
        <XCircle size={48} className="mx-auto mb-4 text-on-muted" />
        <h2 className="text-2xl font-semibold text-on mb-2">
          {t("settings.organization.linkOtherAddress")}
        </h2>
        <p className="text-on-secondary mb-6">
          {t("settings.organization.linkOtherAddressDesc")}
        </p>
        <Button onClick={() => void logout()}>{t("actions.logout")}</Button>
      </div>
    </div>
  );
}

function ErrorCard({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="bg-surface-card p-8 rounded-3xl shadow-md max-w-md w-full text-center">
        <div className="mx-auto w-16 h-16 bg-red-100 text-red-500 rounded-full flex items-center justify-center mb-4">
          <Home size={32} />
        </div>
        <h2 className="text-2xl font-semibold text-on mb-2">
          {t("messages.error")}
        </h2>
        <p className="text-on-secondary mb-6">{message}</p>
        {onRetry && (
          <Button
            type="button"
            variant="secondary"
            onClick={onRetry}
            className="w-full mb-2"
          >
            {t("actions.retry")}
          </Button>
        )}
        <Button
          type="button"
          onClick={() => navigate("/")}
          // The card is `max-w-md` — a narrow surface, where full width is
          // the right shape. What was wrong here was the rest: a raw palette
          // and a size assembled by hand instead of taken from the variant.
          className="w-full"
        >
          {t("actions.close")}
        </Button>
      </div>
    </div>
  );
}

/**
 * The page a join link opens.
 *
 * The invitation mail and the invitations screen name the code as a query
 * (`/join?code=…`); older links in the wild carry it in the path
 * (`/join/QACFAKETOKEN123`) — both arrive here. Whatever the shape, a dead
 * link ends on this page as a message naming the problem and who can issue
 * a fresh link, never as the silent redirect to /login it used to be: a
 * visitor dropped there signs up through /register and mints an organization
 * of their own instead of joining the one that invited them. A link without
 * any code at all keeps the written refusal this screen already answered it
 * with — it is malformed, not expired, and says so.
 */
export default function JoinOrganizationPage() {
  const [searchParams] = useSearchParams();
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, isLoading: isAuthLoading } = useAuthStore();
  const { t } = useTranslation("common");

  const code = searchParams.get("code") ?? token ?? null;
  const [error, setError] = useState<string | null>(null);
  const [linkIsDead, setLinkIsDead] = useState(false);
  // The link is live but was written for another address than the account's.
  const [wrongAccount, setWrongAccount] = useState(false);
  // The request failed without a verdict on the link (outage, network):
  // the reader may ask again.
  const [canRetry, setCanRetry] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const { mutate: joinOrganization } = useJoinOrganization();

  // The join endpoint answers 200 with the organization whether it admitted
  // the caller or they were already in, so "already in" is read here: the
  // organization the reader belonged to before the attempt, against the one
  // that came back. The attempt waits until that is known (or known to be
  // unavailable), because the answer is gone once the join has been judged.
  // Only a signed-in reader has an organization to ask for: a signed-out
  // visitor's request would be refused (a 401 and a token refresh for
  // nothing), and the effect below never waits on it for them.
  const currentOrganization = useOrganization({
    enabled: !isAuthLoading && isAuthenticated,
  });
  const currentOrganizationSettled =
    currentOrganization.isSuccess || currentOrganization.isError;

  // A signed-out visitor has no account to join with — registration with
  // the code attached is the door. But the code is checked first: a dead
  // link says so here, instead of spending the visitor's effort on a form
  // that only refuses at submit.
  const invitationCheck = useInvitationCheck(
    code,
    !isAuthLoading && !isAuthenticated,
  );

  // One attempt per code, latched on a ref that survives React.StrictMode's
  // double effect-invoke: both invocations run in the same commit, before
  // any state has moved, so a guard reading the mutation (isPending/isError)
  // sees an idle mutation on each and a live code gets spent twice — the
  // first POST joins, the second is judged dead, and the card then calls a
  // working link invalid. State cannot latch across the pair; a ref can.
  const attemptedCode = useRef<string | null>(null);

  useEffect(() => {
    // A link without its code is answered by the render below, before any
    // effect could matter — the redirect this page used to fall through to
    // was the reason an invited person landed on the login form.
    if (!code) {
      return;
    }

    if (isAuthLoading) return;

    if (!isAuthenticated || !currentOrganizationSettled) {
      return;
    }

    if (attemptedCode.current === code) {
      return;
    }
    attemptedCode.current = code;
    const organizationBefore = currentOrganization.data?.id;
    joinOrganization(code, {
      onSuccess: (organization) => {
        if (organizationBefore && organization.id === organizationBefore) {
          // Nothing was written and the code stays unspent: say so instead
          // of announcing an arrival that did not happen.
          toast.info(t("settings.organization.alreadyMember"));
          navigate("/");
          return;
        }
        toast.success(t("settings.organization.joinedSuccess"));
        setTimeout(() => {
          navigate("/");
          window.location.reload();
        }, 1000);
      },
      onError: (err: unknown) => {
        logger.error(err);
        // The join endpoint's 404 is the link itself — unknown, spent,
        // withdrawn or expired. All of them are dead for this reader, and
        // the card above says so. A live link written for another address
        // answers 409 and gets its own card; any other refusal (the
        // organization that cannot be left, an outage) keeps the API's own
        // sentence, which names it.
        if (apiErrorStatus(err) === 404) {
          setLinkIsDead(true);
          return;
        }
        if (extractApiErrorCode(err) === "INVITATION_OTHER_ADDRESS") {
          setWrongAccount(true);
          return;
        }
        const status = apiErrorStatus(err);
        setCanRetry(status === null || status >= 500);
        setError(
          extractApiError(err, t("settings.organization.joinRequestFailed")),
        );
      },
    });
  }, [
    code,
    isAuthenticated,
    isAuthLoading,
    currentOrganizationSettled,
    currentOrganization.data?.id,
    navigate,
    joinOrganization,
    t,
    attempt,
  ]);

  const retryJoin = () => {
    attemptedCode.current = null;
    setError(null);
    setCanRetry(false);
    setAttempt((n) => n + 1);
  };

  // No code at all is a malformed link — the written message this screen
  // answers it with, not the silent redirect home that used to strand a
  // signed-out reader on /login.
  if (!code) {
    return <ErrorCard message={t("settings.organization.invalidLink")} />;
  }

  // A code that exists but answers dead — expired, spent, withdrawn — gets
  // the card that names the link and who mints a fresh one.
  if (linkIsDead) {
    return <LinkNotFoundCard />;
  }

  if (wrongAccount && isAuthenticated) {
    return <WrongAccountCard />;
  }

  if (!isAuthenticated) {
    if (invitationCheck.isSuccess) {
      // Live link, no account: registration with the code attached is the
      // way in — the invite travels with them, so the account they create
      // lands in the inviting organization.
      return (
        <Navigate to={`/register?invite=${encodeURIComponent(code)}`} replace />
      );
    }
    if (invitationCheck.isError) {
      if (apiErrorStatus(invitationCheck.error) === 404) {
        return <LinkNotFoundCard />;
      }
      // The check itself failed — an outage, not a verdict on the link.
      return (
        <ErrorCard
          message={extractApiError(
            invitationCheck.error,
            t("settings.organization.joinRequestFailed"),
          )}
          onRetry={() => void invitationCheck.refetch()}
        />
      );
    }
  } else if (error) {
    return (
      <ErrorCard message={error} onRetry={canRetry ? retryJoin : undefined} />
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface p-4">
      <div className="text-center">
        <Loader2 className="animate-spin w-12 h-12 text-primary-600 mx-auto mb-4" />
        <h2 className="text-xl font-semibold text-on">
          {t("settings.organization.joining", {
            defaultValue: "Joining organization...",
          })}
        </h2>
        <p className="text-on-secondary mt-2">{t("messages.loading")}</p>
      </div>
    </div>
  );
}
