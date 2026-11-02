import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useInitStatus } from "@/hooks/useInitStatus";
import { extractApiError, extractApiErrorField } from "@/lib/errors";
import { firstBrokenRule } from "@/lib/passwordPolicy";
import { PasswordRules } from "@/pages/PasswordRules";
import { useAuthStore } from "@/store/authStore";

type FieldErrors = { current?: string; next?: string; confirm?: string };

/**
 * A new password, asked for together with the current one.
 *
 * Each refusal is said at the field it is about. A success ends the session
 * (the server has invalidated it), so the confirmation is given by the
 * sign-in screen the reader lands on. On the public demo the password is not
 * the visitor's to change; the card says so instead of offering a form the
 * server would refuse.
 */
export default function ProfilePasswordCard({
  onDirtyChange,
}: {
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation("common");
  const { t: tAuth } = useTranslation("auth");
  const { data: initStatus, isPending } = useInitStatus();
  const changePassword = useAuthStore((state) => state.changePassword);

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [isSaving, setIsSaving] = useState(false);

  const isDirty = Boolean(current || next || confirm);
  // A refusal belongs to the value it was about: typing a new one takes it
  // off the field instead of leaving it to contradict what is there now.
  const editing =
    (field: keyof FieldErrors, setValue: (value: string) => void) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setValue(e.target.value);
      setErrors((prev) =>
        prev[field] ? { ...prev, [field]: undefined } : prev,
      );
    };
  useEffect(() => {
    onDirtyChange(isDirty);
    return () => onDirtyChange(false);
  }, [isDirty, onDirtyChange]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const found: FieldErrors = {};
    if (!current)
      found.current = t("settings.profile.password.currentRequired");
    const broken = firstBrokenRule(next);
    if (broken) found.next = tAuth(`passwordPolicy.errors.${broken}` as const);
    else if (next !== confirm) found.confirm = tAuth("reset.passwordMismatch");
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setIsSaving(true);
    try {
      await changePassword(current, next);
    } catch (error) {
      if (extractApiErrorField(error, "field") === "current_password") {
        setErrors({ current: t("settings.profile.password.currentWrong") });
      } else {
        toast.error(extractApiError(error, t("messages.error")));
      }
      setIsSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.profile.password.title")}</CardTitle>
        {!isPending && !initStatus?.is_demo && (
          <CardDescription>
            {t("settings.profile.password.hint")}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        {isPending ? null : initStatus?.is_demo ? (
          <div className="flex items-start gap-2.5 rounded-lg bg-blue-50 px-3 py-2.5 text-sm text-on-info">
            <Lock size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>{t("settings.profile.password.demoLocked")}</p>
          </div>
        ) : (
          <form
            onSubmit={handleSubmit}
            className="space-y-4 sm:max-w-md"
            noValidate
          >
            <Input
              id="profile-current-password"
              label={t("settings.profile.password.current")}
              type="password"
              autoComplete="current-password"
              aria-required
              value={current}
              onChange={editing("current", setCurrent)}
              error={errors.current}
            />
            <Input
              id="profile-new-password"
              label={tAuth("reset.newPasswordLabel")}
              type="password"
              autoComplete="new-password"
              aria-required
              value={next}
              onChange={editing("next", setNext)}
              error={errors.next}
            />
            <PasswordRules value={next} />
            <Input
              id="profile-confirm-password"
              label={tAuth("reset.confirmPasswordLabel")}
              type="password"
              autoComplete="new-password"
              aria-required
              value={confirm}
              onChange={editing("confirm", setConfirm)}
              error={errors.confirm}
            />
            <div className="flex justify-end">
              <Button type="submit" disabled={isSaving} isLoading={isSaving}>
                {t("settings.profile.password.submit")}
              </Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
