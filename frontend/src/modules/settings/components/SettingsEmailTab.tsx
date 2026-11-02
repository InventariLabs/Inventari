import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import {
  Mail,
  Save,
  Info,
  ChevronDown,
  AlertTriangle,
  Inbox,
} from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { QueryFailure } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import { useInitStatus } from "@/hooks/useInitStatus";

import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import {
  useOrganization,
  useUpdateOrganization,
  useTestEmail,
} from "@/modules/settings/hooks/useOrganization";

type SmtpEncryption = "none" | "starttls" | "ssl";

interface SMTPSettings {
  host: string;
  port: number;
  /**
   * Explicit, because the port used to decide it: the backend called
   * STARTTLS only on 587, so a server on 465 — the standard TLS port — sent
   * the login and the message in the clear with nothing on screen saying so.
   */
  encryption: SmtpEncryption;
  user: string;
  password: string;
  from_email: string;
  from_name: string;
}

/** What the backend infers for a configuration saved before the field existed. */
const encryptionImpliedByPort = (port: number): SmtpEncryption => {
  if (port === 465) return "ssl";
  if (port === 587) return "starttls";
  return "none";
};

/** What is wrong with the form, field by field; empty when it can be saved. */
function validateSmtp(
  settings: SMTPSettings,
  t: TFunction<"common">,
): Partial<Record<keyof SMTPSettings, string>> {
  const next: Partial<Record<keyof SMTPSettings, string>> = {};
  if (!settings.host.trim()) {
    next.host = t("settings.smtp.errorHostRequired");
  }
  const port = Number(settings.port);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    next.port = t("settings.smtp.errorPortRange");
  }
  // Neither is required: a relay that asks for no login is valid. Half a
  // login is not — the server would be offered one without the other, and
  // the card would read "Not configured" with nothing saying why.
  if (settings.user && !settings.password) {
    next.password = t("settings.smtp.errorUserWithoutPassword");
  } else if (settings.password && !settings.user) {
    next.user = t("settings.smtp.errorPasswordWithoutUser");
  }
  // from_email is optional; if non-empty it will be validated by the
  // BE SmtpConfig schema (EmailStr) which returns 422. We avoid a
  // redundant client-side regex so the two checks cannot drift apart.
  return next;
}

export default function SettingsEmailTab() {
  const { t } = useTranslation(["common"]);
  const [isOpen, setIsOpen] = useState(false);
  // The instance's own declaration, not a guess from the inbox URL: on the
  // public demo the backend refuses to save these settings and never uses
  // stored ones, so the form would be a control that does nothing. The
  // notice replaces it and points at where mail actually ends up.
  const { data: initStatus } = useInitStatus();
  const isDemo = initStatus?.is_demo === true;
  const demoInboxUrl = initStatus?.demo_inbox_url;

  const {
    data: organization,
    isLoading: isLoadingOrganization,
    isError: organizationFailed,
    error: organizationError,
    refetch: refetchOrganization,
  } = useOrganization();
  // The server's answer, not the organization's own SMTP block: an
  // installation-wide mail server sends for organizations that have none of
  // their own — the same reading the invitations section takes.
  const canSendEmail = organization?.can_send_email === true;
  const updateSettingsMutation = useUpdateOrganization();
  const testEmailMutation = useTestEmail();

  const [smtpSettings, setSmtpSettings] = useState<SMTPSettings>({
    host: "",
    port: 587,
    encryption: "starttls",
    user: "",
    password: "",
    from_email: "",
    from_name: "Inventari",
  });
  const [errors, setErrors] = useState<
    Partial<Record<keyof SMTPSettings, string>>
  >({});

  useEffect(() => {
    const smtp = organization?.settings?.smtp as
      Record<string, unknown> | undefined;
    if (smtp) {
      const port = (smtp.port as number) || 587;
      setSmtpSettings({
        host: (smtp.host as string) || "",
        port,
        encryption:
          (smtp.encryption as SmtpEncryption) ?? encryptionImpliedByPort(port),
        user: (smtp.user as string) || "",
        password: (smtp.password as string) || "",
        from_email: (smtp.from_email as string) || "",
        from_name: (smtp.from_name as string) || "Inventari",
      });
    }
  }, [organization]);

  const validate = (): boolean => {
    const next = validateSmtp(smtpSettings, t);
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSave = () => {
    if (!validate()) return;
    const currentSettings = organization?.settings || {};
    updateSettingsMutation.mutate(
      {
        settings: {
          ...(currentSettings as Record<string, unknown>),
          smtp: smtpSettings,
        },
      },
      {
        onSuccess: () => toast.success(t("messages.success")),
        onError: (err: unknown) =>
          toast.error(extractApiError(err, t("messages.error"))),
      },
    );
  };

  const handleTestEmail = () => {
    if (!validate()) return;
    testEmailMutation.mutate(smtpSettings, {
      onSuccess: () => toast.success(t("settings.smtp.testSuccess")),
      onError: (err: unknown) =>
        toast.error(extractApiError(err, t("settings.smtp.testError"))),
    });
  };

  // A demo publishes its administrator login, and the backend refuses these
  // settings there (they cannot be saved and stored ones are never used), so
  // the form would be a control that does nothing. The card says what happens
  // instead. Checked before the organization read: the notice is about the
  // instance, not about the organization.
  if (isDemo) {
    return (
      <Card className="p-6">
        <div className="flex items-center gap-4 min-w-0">
          <div className="w-10 h-10 bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 rounded-xl flex items-center justify-center shrink-0">
            <Mail size={20} strokeWidth={2.5} />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-on leading-tight">
              {t("settings.smtp.title")}
            </h2>
            <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-0.5">
              {t("settings.smtp.subtitle")}
            </p>
          </div>
        </div>
        <div className="mt-6 flex items-start gap-2.5 rounded-lg bg-blue-50 px-3 py-2.5 text-xs text-on-info">
          <Inbox size={16} className="mt-px shrink-0" aria-hidden="true" />
          <p>
            {t("settings.smtp.demoNotice")}{" "}
            {demoInboxUrl && (
              <a
                href={demoInboxUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium underline decoration-2 underline-offset-4"
              >
                {t("settings.smtp.demoInboxLink")}
              </a>
            )}
          </p>
        </div>
      </Card>
    );
  }

  // The badge below reads the organization's answer, so without one it says
  // NOT CONFIGURED — a claim about the installation, and the reader's next
  // move is to type a mail server over the working one. The form is the same
  // trap with the fields blank, so neither is shown until the read succeeds.
  if (organizationFailed) {
    return (
      <Card className="p-6">
        <QueryFailure
          error={organizationError}
          onRetry={() => refetchOrganization()}
        />
      </Card>
    );
  }

  return (
    <Card className="p-6">
      {" "}
      <Button
        size="content"
        variant="ghost"
        onClick={() => setIsOpen(!isOpen)}
        className="min-h-11 md:min-h-0 min-w-11 md:min-w-0 w-full px-0 justify-between gap-4 text-left"
      >
        {/* min-w-0: the text yields to the badge and the chevron, which are
            the only controls and must stay on a phone screen. */}
        <div className="flex items-center gap-4 min-w-0">
          <div className="w-10 h-10 bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 rounded-xl flex items-center justify-center shrink-0">
            <Mail size={20} strokeWidth={2.5} />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-on leading-tight">
              {t("settings.smtp.title")}
            </h2>
            <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mt-0.5">
              {t("settings.smtp.subtitle")}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {/* Whether this installation can send mail at all is the first
              thing the page is opened to find out. It used to require
              expanding the accordion and reading the fields — and the fields
              are the organization's own, so an installation-wide server left
              them empty while mail went out fine. */}
          <Badge variant={canSendEmail ? "success" : "secondary"}>
            {canSendEmail
              ? t("settings.smtp.statusConfigured")
              : t("settings.smtp.statusNotConfigured")}
          </Badge>
          <ChevronDown
            size={18}
            className={cn(
              "text-on-muted transition-transform duration-200 shrink-0",
              isOpen && "rotate-180",
            )}
          />
        </div>
      </Button>
      {isOpen && (
        <div className="mt-6 pt-6 border-t border-border space-y-5">
          {/* What this configuration is for comes first; the actions come
              after the fields they act on. */}
          <p className="text-xs text-on-muted flex items-start gap-2">
            <Info size={13} className="shrink-0 mt-0.5" />
            {t("settings.smtp.help")}
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 items-end lg:grid-cols-3 gap-5">
            <Input
              label={t("settings.smtp.host")}
              type="text"
              required
              value={smtpSettings.host}
              onChange={(e) =>
                setSmtpSettings({ ...smtpSettings, host: e.target.value })
              }
              placeholder="smtp.gmail.com"
              error={errors.host}
            />
            <Input
              label={t("settings.smtp.port")}
              type="number"
              min={1}
              max={65535}
              value={smtpSettings.port}
              onChange={(e) =>
                setSmtpSettings({
                  ...smtpSettings,
                  port: parseInt(e.target.value) || 587,
                })
              }
              error={errors.port}
            />
            <Select
              label={t("settings.smtp.encryption")}
              value={smtpSettings.encryption}
              onChange={(value) =>
                setSmtpSettings({
                  ...smtpSettings,
                  encryption: value as SmtpEncryption,
                })
              }
              options={[
                {
                  id: "starttls",
                  name: t("settings.smtp.encryptionStarttls"),
                },
                { id: "ssl", name: t("settings.smtp.encryptionSsl") },
                { id: "none", name: t("settings.smtp.encryptionNone") },
              ]}
            />
            <Input
              label={t("settings.smtp.user")}
              type="text"
              value={smtpSettings.user}
              onChange={(e) =>
                setSmtpSettings({ ...smtpSettings, user: e.target.value })
              }
              error={errors.user}
            />
            <Input
              label={t("settings.smtp.password")}
              type="password"
              value={smtpSettings.password}
              onChange={(e) =>
                setSmtpSettings({ ...smtpSettings, password: e.target.value })
              }
              error={errors.password}
            />
            <Input
              label={t("settings.smtp.fromEmail")}
              type="email"
              value={smtpSettings.from_email}
              onChange={(e) =>
                setSmtpSettings({
                  ...smtpSettings,
                  from_email: e.target.value,
                })
              }
              placeholder="no-reply@example.com"
              error={errors.from_email}
            />
            <Input
              label={t("settings.smtp.fromName")}
              type="text"
              value={smtpSettings.from_name}
              onChange={(e) =>
                setSmtpSettings({
                  ...smtpSettings,
                  from_name: e.target.value,
                })
              }
            />
          </div>

          {smtpSettings.encryption === "none" && (
            <p className="text-xs font-medium text-on-warning flex items-center gap-2">
              <AlertTriangle size={14} className="shrink-0" />
              {t("settings.smtp.encryptionHelp")}
            </p>
          )}

          <div className="flex flex-wrap justify-end gap-2">
            <Button
              variant="secondary"
              onClick={handleTestEmail}
              disabled={testEmailMutation.isPending || !smtpSettings.host}
              isLoading={testEmailMutation.isPending}
              leftIcon={<Mail size={16} />}
              className="text-xs"
            >
              {t("settings.smtp.test")}
            </Button>
            <Button
              onClick={handleSave}
              disabled={
                updateSettingsMutation.isPending || isLoadingOrganization
              }
              isLoading={updateSettingsMutation.isPending}
              leftIcon={<Save size={16} />}
              className="text-xs"
            >
              {t("settings.smtp.save")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
