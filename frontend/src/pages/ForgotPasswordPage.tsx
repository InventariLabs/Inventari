import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Mail, ArrowLeft } from "lucide-react";
import { toast } from "sonner";

import { authApi } from "@/lib/api/auth";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { AuthLayout } from "./AuthLayout";

export default function ForgotPasswordPage() {
  const { t } = useTranslation("auth");
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [emailDelivers, setEmailDelivers] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    try {
      const result = await authApi.requestPasswordReset(email);
      setEmailDelivers(result.email_delivery_configured);
      setSubmitted(true);
    } catch (error) {
      // The endpoint never reveals whether the email exists; what it does say
      // is the installation's own refusal (the public demo has no reset).
      toast.error(
        extractApiError(
          error,
          t("reset.requestError", {
            defaultValue: "Could not send reset email. Please try again later.",
          }),
        ),
      );
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

        {submitted ? (
          // An installation with no SMTP sends nothing, and telling the reader
          // to check an inbox leaves them waiting for a letter that will never
          // arrive. The flag describes the installation, not the address, so
          // saying it reveals nothing about who has an account here.
          <div className="text-center py-4" data-testid="forgot-success">
            <div className="w-12 h-12 rounded-full bg-accent-100 text-accent-600 flex items-center justify-center mx-auto mb-4">
              <Mail size={20} />
            </div>
            <h2 className="text-lg font-semibold text-on mb-2">
              {emailDelivers
                ? t("reset.requestSentTitle", {
                    defaultValue: "Check your inbox",
                  })
                : t("reset.noEmailTitle", {
                    defaultValue: "This installation does not send email",
                  })}
            </h2>
            <p className="text-sm text-on-muted leading-relaxed">
              {emailDelivers
                ? t("reset.requestSentBody", {
                    defaultValue:
                      "If an account exists for that address, we sent a password reset link. It expires in 30 minutes.",
                  })
                : t("reset.noEmailBody", {
                    defaultValue:
                      "No reset link was sent, because email is not configured here. Ask an administrator to set your password or to configure email in Settings.",
                  })}
            </p>
          </div>
        ) : (
          <>
            <div className="mb-6">
              <h2 className="text-lg font-semibold text-on mb-2 leading-none">
                {t("reset.title", { defaultValue: "Forgot your password?" })}
              </h2>
              <p className="text-sm text-on-muted leading-relaxed">
                {t("reset.subtitle", {
                  defaultValue:
                    "Enter your email and we'll send a link to reset your password.",
                })}
              </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <Input
                id="email"
                label={t("reset.emailLabel", { defaultValue: "Email" })}
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                leftIcon={<Mail size={16} />}
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
                  {t("reset.submitButton", {
                    defaultValue: "Send reset link",
                  })}
                </Button>
              </div>
            </form>
          </>
        )}
      </Card>
    </AuthLayout>
  );
}
