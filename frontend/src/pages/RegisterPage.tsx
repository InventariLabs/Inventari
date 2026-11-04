import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/store/authStore";
import { Mail, Lock, User, CheckCircle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { queryKeys } from "@/hooks/queries/keys";
import { useInitStatus } from "@/hooks/useInitStatus";
import { AuthLayout } from "./AuthLayout";
import { PasswordRules } from "./PasswordRules";
import { firstBrokenRule } from "@/lib/passwordPolicy";
import { extractApiError } from "@/lib/errors";
import { authApi } from "@/lib/api/auth";
import { organizationsApi } from "@/lib/api/organizations";

/**
 * A link for somebody else's account, opened on a device where another
 * account is signed in: the new account is created and the screen then returns
 * to the session that was already there. Say whose session that is, and offer
 * the way out.
 */
function OtherSessionNotice() {
  const { t } = useTranslation("auth");
  const [searchParams] = useSearchParams();
  const signedIn = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const arrivedByLink = searchParams.has("token") || searchParams.has("invite");
  if (!signedIn || !arrivedByLink) return null;
  return (
    <div
      role="status"
      className="mt-3 flex flex-col items-start gap-2 rounded-lg border border-border bg-surface-raised p-3 text-sm text-on-secondary"
    >
      <p>{t("signedInElsewhere", { email: signedIn.email })}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void logout()}
      >
        {t("signOutFirst")}
      </Button>
    </div>
  );
}

export default function RegisterPage() {
  const { t } = useTranslation("auth");
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const inviteCode = searchParams.get("invite");

  const queryClient = useQueryClient();
  const { data: initStatus } = useInitStatus(!token);

  const isFirstUser = initStatus?.is_initialized === false;
  const showFullForm = Boolean(token || isFirstUser || inviteCode);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  // What the link already knows about the person arriving through it: the
  // organization, inviter, role and address of an invitation; the address and
  // name given in the request an administrator approved. Shown and prefilled
  // so the form does not open as a blank stranger's.
  const invitation = useQuery({
    queryKey: queryKeys.admin.registerInvitation(inviteCode),
    queryFn: () => organizationsApi.checkInvitation(inviteCode ?? ""),
    enabled: Boolean(inviteCode),
    retry: false,
  }).data;
  const approvedRequest = useQuery({
    queryKey: queryKeys.admin.registerApprovedRequest(token),
    queryFn: () => authApi.getRegistrationLink(token ?? ""),
    enabled: Boolean(token),
    retry: false,
  }).data;

  // The API names a built-in level by its key (`user`, `viewer`...) and a
  // custom role by the name its author gave it. Every other screen says
  // "Member" for `user`, so this one translates the key and leaves a custom
  // name as it was typed.
  const invitedRole = invitation?.role;
  const invitationVars = {
    organization: invitation?.organization_name,
    inviter: invitation?.inviter_name,
    role: invitedRole
      ? t(`common:settings.organization.memberRoles.${invitedRole}`, {
          defaultValue: invitedRole,
        })
      : undefined,
  };

  useEffect(() => {
    if (invitation?.invited_email) setEmail(invitation.invited_email);
  }, [invitation?.invited_email]);
  useEffect(() => {
    if (approvedRequest?.full_name) setFullName(approvedRequest.full_name);
  }, [approvedRequest?.full_name]);

  const {
    requestRegistration,
    completeRegistration,
    register: registerDirect,
  } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    // The same four rules the backend applies, said before the request
    // rather than after it — the field promised "min. 6 characters", which
    // is not a password the API would accept.
    const broken = showFullForm ? firstBrokenRule(password) : null;
    if (broken) {
      toast.error(t(`passwordPolicy.errors.${broken}` as const));
      setIsLoading(false);
      return;
    }

    if (showFullForm && password !== confirmPassword) {
      toast.error(
        t("reset.passwordMismatch", {
          defaultValue: "Passwords don't match",
        }),
      );
      setIsLoading(false);
      return;
    }

    try {
      if (isFirstUser) {
        await registerDirect(email, password, fullName || undefined);
        // The installation has an account now: the status is cached for good
        // (staleTime Infinity), so without this /login keeps offering the
        // first-account setup until a reload.
        await queryClient.invalidateQueries({
          queryKey: queryKeys.admin.initStatus,
        });
        toast.success(t("accountCreated"));
        navigate("/login", { state: { email } });
      } else if (inviteCode) {
        await registerDirect(
          email,
          password,
          fullName || undefined,
          inviteCode,
        );
        toast.success(
          t("common:settings.organization.joinedSuccess", {
            defaultValue: "Account created & joined organization!",
          }),
        );
        navigate("/login", { state: { email } });
      } else if (token) {
        await completeRegistration(token, password, fullName || undefined);
        toast.success(t("registrationCompleted"));
        navigate("/login", {
          state: { email: approvedRequest?.email ?? email },
        });
      } else {
        await requestRegistration(email, fullName || undefined);
        // No toast: the card that replaces this form is the confirmation,
        // and a toast repeating its headline is the same sentence twice.
        setIsSubmitted(true);
      }
    } catch (error) {
      // The API's sentence names the actual refusal — an invitation that
      // does not cover this address, a server that could not cope. Throwing
      // it away told someone whose data was perfectly fine to "check your
      // data", and the real problem went unnamed.
      if (showFullForm) {
        toast.error(extractApiError(error, t("registrationFailed")));
      } else {
        toast.error(extractApiError(error, t("requestFailed")));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const getTitle = () => {
    if (isFirstUser || inviteCode) return t("createAccount");
    if (token) return t("completeRegistration");
    return t("requestAccess");
  };

  const getButtonLabel = () => {
    if (isLoading) return t("creatingAccount");
    if (isFirstUser || inviteCode) return t("createAccount");
    if (token) return t("completeRegistration");
    return t("requestAccess");
  };

  if (isSubmitted && !token && !isFirstUser) {
    return (
      <AuthLayout>
        <Card className="p-6 sm:p-8 border border-transparent shadow-lg">
          <div className="mb-8 text-center sm:text-left">
            <div className="w-12 h-12 bg-primary-100 rounded-full flex items-center justify-center mx-auto sm:mx-0 mb-4">
              <CheckCircle className="text-primary-600" size={24} />
            </div>
            {/* One sentence for what happened, one for what happens next.
                The card used to print the headline again underneath itself,
                and to offer sign-in to somebody who has no account to sign
                in to — the approval mails a link instead. */}
            <h2 className="text-xl font-semibold text-on mb-3 leading-none">
              {t("requestSubmitted")}
            </h2>
            <p className="text-sm text-on-secondary">
              {initStatus?.email_delivery_configured === false
                ? t("requestApprovalFlowNoMail", { email })
                : t("requestApprovalFlow", { email })}
            </p>
          </div>
        </Card>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <Card className="p-6 sm:p-8 border border-transparent shadow-lg">
        <div className="mb-8 text-center sm:text-left">
          <h2 className="text-xl font-semibold text-on mb-3 leading-none">
            {getTitle()}
          </h2>
          <p className="flex flex-wrap items-center gap-x-1 text-xs font-medium text-on-muted">
            {t("or")}
            <Link
              to="/login"
              className="inline-flex min-h-11 items-center md:min-h-0 text-primary-700 hover:text-primary-800 dark:text-primary-500 dark:hover:text-primary-500 transition-colors underline decoration-2 underline-offset-4"
            >
              {t("loginToExisting")}
            </Link>
          </p>
          {/* The requester must know what an approved request actually
              creates: an account with an organization of its own, not a
              place inside the one they were hoping to join. Only an
              invitation admits into an existing organization (USER_GUIDE
              §1.1). */}
          {invitation?.organization_name && (
            <p className="text-sm text-on-secondary mt-3">
              {invitation.inviter_name
                ? t("inviteContext", invitationVars)
                : t("inviteContextNoInviter", invitationVars)}
            </p>
          )}
          {approvedRequest && (
            <p className="text-sm text-on-secondary mt-3">
              {t("completeContext", { email: approvedRequest.email })}
            </p>
          )}
          <OtherSessionNotice />
          {!showFullForm && (
            <p className="text-sm text-on-secondary mt-3">
              {t("requestAccessWhatYouGet")}
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {!token && (
            <Input
              id="email"
              label={t("register.emailLabel")}
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="jan@example.com"
              leftIcon={<Mail size={16} />}
              className="h-12 font-semibold"
            />
          )}

          <Input
            id="fullName"
            label={t("register.nameLabel")}
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder={t("register.namePlaceholder")}
            leftIcon={<User size={16} />}
            className="h-12 font-semibold"
          />

          {showFullForm && (
            <Input
              id="password"
              label={t("register.passwordLabel")}
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              leftIcon={<Lock size={16} />}
              className="h-12 font-semibold"
            />
          )}

          {showFullForm && <PasswordRules value={password} />}

          {showFullForm && (
            <Input
              id="confirmPassword"
              label={t("reset.confirmPasswordLabel", {
                defaultValue: "Confirm password",
              })}
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder={t("register.confirmPasswordPlaceholder", {
                defaultValue: "Repeat your password",
              })}
              leftIcon={<Lock size={16} />}
              className="h-12 font-semibold"
            />
          )}

          <div className="pt-2">
            <Button
              size="content"
              type="submit"
              disabled={isLoading}
              isLoading={isLoading}
              className="w-full h-12 text-base shadow-md shadow-accent-600/10 font-semibold tracking-tight"
            >
              {getButtonLabel()}
            </Button>
          </div>
        </form>
      </Card>
    </AuthLayout>
  );
}
