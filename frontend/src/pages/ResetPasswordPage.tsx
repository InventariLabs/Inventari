import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Lock, ArrowLeft, CheckCircle2, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { authApi } from "@/lib/api/auth";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { AuthLayout } from "./AuthLayout";
import { SignedInNotice } from "./SignedInNotice";
import { PasswordRules } from "./PasswordRules";
import { firstBrokenRule } from "@/lib/passwordPolicy";
import { apiErrorStatus, isServerRefusal } from "@/lib/errors";

/**
 * Whether a failed check or save condemns the link. A 4xx is the server
 * refusing this token — except a 429, which refuses the pace of the requests
 * from this address and says nothing about the link: read as a dead link, it
 * sent a reader holding a perfectly good one off to ask for another.
 */
function refusesTheLink(error: unknown): boolean {
  return isServerRefusal(error) && apiErrorStatus(error) !== 429;
}

export default function ResetPasswordPage() {
  const { t } = useTranslation("auth");
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [done, setDone] = useState(false);
  // A refusal stays on the screen as a state of this page — a toast was
  // gone before anyone had read it, and the form below went on asking for
  // a password a dead link can never save.
  const [linkInvalid, setLinkInvalid] = useState(false);
  // The save did not happen for a reason that is not the link — the server
  // broke, the network dropped, or too many attempts came from this address:
  // the link may be perfectly good, so the form stays and says which.
  const [failure, setFailure] = useState<
    "requestFailed" | "tooManyAttempts" | null
  >(null);
  // A link from an old e-mail is the usual way to land here with a token that
  // is spent or expired: ask before showing a form for a password it can
  // never save. Until the answer comes the card holds no form, so a dead link
  // never flashes one.
  const [checking, setChecking] = useState(Boolean(token));

  useEffect(() => {
    if (!token) {
      setLinkInvalid(true);
      return;
    }
    let current = true;
    authApi
      .checkPasswordReset(token)
      .catch((error: unknown) => {
        // Only a refusal of the token condemns the link; a server or network
        // failure, or a rate limit, leaves the form, and submitting it
        // reports what happened.
        if (current && refusesTheLink(error)) setLinkInvalid(true);
      })
      .finally(() => {
        if (current) setChecking(false);
      });
    return () => {
      current = false;
    };
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Every rule, named: the server applies all four, and a client that
    // checks only the length sends the reader back with "invalid" for a rule
    // nothing on the screen ever mentioned.
    const broken = firstBrokenRule(newPassword);
    if (broken) {
      toast.error(t(`passwordPolicy.errors.${broken}` as const));
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(
        t("reset.passwordMismatch", {
          defaultValue: "Passwords do not match.",
        }),
      );
      return;
    }
    if (!token) {
      setLinkInvalid(true);
      return;
    }
    setIsLoading(true);
    setFailure(null);
    try {
      await authApi.confirmPasswordReset(token, newPassword);
      setDone(true);
    } catch (error) {
      if (refusesTheLink(error)) {
        setLinkInvalid(true);
      } else {
        setFailure(
          apiErrorStatus(error) === 429 ? "tooManyAttempts" : "requestFailed",
        );
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <Card className="p-6 sm:p-8 shadow-lg">
        <Link
          to="/login"
          className="inline-flex min-h-11 items-center gap-1 text-xs font-medium text-on-muted hover:text-primary-600 transition-colors mb-4 md:min-h-0 md:mb-6"
        >
          <ArrowLeft size={14} />
          {t("reset.backToLogin", { defaultValue: "Back to login" })}
        </Link>

        <SignedInNotice />

        {done ? (
          <div className="text-center py-4" data-testid="reset-success">
            <div className="w-12 h-12 rounded-full bg-accent-100 text-accent-600 flex items-center justify-center mx-auto mb-4">
              <CheckCircle2 size={20} />
            </div>
            <h2 className="text-lg font-semibold text-on mb-2">
              {t("reset.successTitle", {
                defaultValue: "Password updated",
              })}
            </h2>
            <p className="text-sm text-on-muted leading-relaxed mb-6">
              {t("reset.successBody", {
                defaultValue: "You can now log in with your new password.",
              })}
            </p>
            <Button
              size="content"
              type="button"
              onClick={() => navigate("/login", { replace: true })}
              className="w-full h-12 text-base font-semibold tracking-tight"
            >
              {t("reset.goToLogin", { defaultValue: "Go to login" })}
            </Button>
          </div>
        ) : checking && !linkInvalid ? (
          // Said, not just held: a blank card on a slow connection read as
          // a page that had failed to load.
          <p
            role="status"
            data-testid="reset-checking"
            className="flex items-center gap-2 py-4 text-sm text-on-muted"
          >
            <Loader2
              size={16}
              className="shrink-0 animate-spin"
              aria-hidden="true"
            />
            {t("reset.checking")}
          </p>
        ) : linkInvalid ? (
          <div className="py-4" data-testid="reset-invalid-link">
            <h2 className="text-lg font-semibold text-on mb-2">
              {t("reset.invalidToken", {
                defaultValue: "Invalid or expired reset link.",
              })}
            </h2>
            <p className="text-sm text-on-muted leading-relaxed">
              {t("reset.invalidTokenWhy", {
                defaultValue:
                  "Reset links work once and expire 30 minutes after they are sent.",
              })}
            </p>
            {/* The way out, not just the verdict — the attestation screen's
                refusal card is the pattern: say who can reissue the link. */}
            <p className="mt-3 text-sm leading-relaxed">
              {/* A reset link is usually opened from an e-mail on a phone:
                  the same 44 px target and contrast as the login page's
                  "Forgot password?" link. */}
              <Link
                to="/forgot-password"
                className="inline-flex min-h-11 items-center md:min-h-0 font-medium text-primary-700 hover:text-primary-800 dark:text-primary-500 dark:hover:text-primary-500 underline decoration-2 underline-offset-4 transition-colors"
              >
                {t("reset.invalidTokenNext", {
                  defaultValue: "Request a fresh reset link.",
                })}
              </Link>
            </p>
          </div>
        ) : (
          <>
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-on mb-2 leading-none">
                {t("reset.title", { defaultValue: "Reset your password" })}
              </h2>
              <p className="text-sm text-on-muted leading-relaxed">
                {t("reset.chooseNew", {
                  defaultValue: "Choose a new password for your account.",
                })}
              </p>
            </div>

            {failure && (
              <p
                role="alert"
                className="mb-4 text-sm text-red-600 dark:text-red-400"
                data-testid="reset-request-failed"
              >
                {failure === "tooManyAttempts"
                  ? t("reset.tooManyAttempts")
                  : t("reset.requestFailed", {
                      defaultValue:
                        "The password could not be saved because of a problem on our side. Your link may still be valid — try again.",
                    })}
              </p>
            )}
            <form onSubmit={handleSubmit} className="space-y-5">
              <Input
                id="new-password"
                label={t("reset.newPasswordLabel", {
                  defaultValue: "New password",
                })}
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••"
                leftIcon={<Lock size={16} />}
                className="h-12 font-semibold"
              />
              <PasswordRules value={newPassword} />
              <Input
                id="confirm-password"
                label={t("reset.confirmPasswordLabel", {
                  defaultValue: "Confirm password",
                })}
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                leftIcon={<Lock size={16} />}
                className="h-12 font-semibold"
              />

              <div className="pt-2">
                <Button
                  size="content"
                  type="submit"
                  disabled={isLoading}
                  isLoading={isLoading}
                  className="w-full h-12 text-base shadow-md shadow-accent-600/10 font-semibold tracking-tight"
                >
                  {t("reset.setPasswordButton")}
                </Button>
              </div>
            </form>
          </>
        )}
      </Card>
    </AuthLayout>
  );
}
