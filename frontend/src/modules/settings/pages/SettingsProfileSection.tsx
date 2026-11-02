import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useFormGuard } from "@/hooks/useFormGuard";
import { useLanguagePreference } from "@/hooks/useLanguagePreference";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { LANGUAGES, communityCoverage, type Language } from "@/i18n/languages";
import { extractApiError } from "@/lib/errors";
import { useAuthStore } from "@/store/authStore";
import ProfilePasswordCard from "../components/ProfilePasswordCard";

/**
 * My profile — /settings/profile, open to every member.
 *
 * The signed-in person's own name, language and password. The e-mail address
 * is shown but not editable: a new address needs confirming before it can be
 * trusted for sign-in, and the server takes no address here.
 */
export default function SettingsProfileSection() {
  const { t } = useTranslation("common");
  const { setHeader } = useModulePageHeader();

  // One gate for the page, fed by both cards that can hold unsaved work —
  // the same arrangement as the organization screen, and for the same
  // reason: the first card going clean must not disarm the second.
  const [dirtyCards, setDirtyCards] = useState({
    name: false,
    password: false,
  });
  const reportNameDirty = useCallback(
    (value: boolean) =>
      setDirtyCards((prev) =>
        prev.name === value ? prev : { ...prev, name: value },
      ),
    [],
  );
  const reportPasswordDirty = useCallback(
    (value: boolean) =>
      setDirtyCards((prev) =>
        prev.password === value ? prev : { ...prev, password: value },
      ),
    [],
  );
  useFormGuard(
    dirtyCards.name || dirtyCards.password,
    t("settings.profile.guardName"),
  );

  useEffect(() => {
    setHeader({
      title: t("settings.tabs.profile"),
      subtitle: t("settings.profile.subtitle"),
    });
  }, [t, setHeader]);

  return (
    <div className="space-y-6 pb-32 animate-in fade-in slide-in-from-bottom-2 duration-300">
      <NameCard onDirtyChange={reportNameDirty} />
      <LanguageCard />
      <ProfilePasswordCard onDirtyChange={reportPasswordDirty} />
    </div>
  );
}

/** The name the app and the colleagues see. */
function NameCard({
  onDirtyChange,
}: {
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation("common");
  const user = useAuthStore((state) => state.user);
  const saveFullName = useAuthStore((state) => state.saveFullName);
  const saved = user?.full_name ?? "";
  const [name, setName] = useState(saved);
  const [isSaving, setIsSaving] = useState(false);

  const trimmed = name.trim();
  const isDirty = trimmed !== saved;
  const emptyError =
    isDirty && !trimmed ? t("settings.profile.nameRequired") : undefined;

  useEffect(() => {
    onDirtyChange(isDirty);
    return () => onDirtyChange(false);
  }, [isDirty, onDirtyChange]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!trimmed) return;
    setIsSaving(true);
    try {
      await saveFullName(trimmed);
      setName(trimmed);
      toast.success(t("settings.profile.nameSaved"));
    } catch (error) {
      toast.error(extractApiError(error, t("messages.error")));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.profile.nameTitle")}</CardTitle>
        <CardDescription>
          {t("settings.profile.nameHint", { email: user?.email ?? "" })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4 sm:max-w-md">
          <Input
            id="profile-full-name"
            label={t("settings.profile.fullName")}
            autoComplete="name"
            aria-required
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={emptyError}
          />
          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={!isDirty || !trimmed || isSaving}
              isLoading={isSaving}
            >
              {t("actions.save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

/**
 * The interface language — the same setting as the selector in the top bar,
 * read and written through the same hook, so the two always agree.
 */
function LanguageCard() {
  const { t } = useTranslation("common");
  const { language, changeLanguage } = useLanguagePreference();

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("settings.language")}</CardTitle>
        <CardDescription>{t("settings.profile.languageHint")}</CardDescription>
      </CardHeader>
      <CardContent>
        <NativeSelect
          id="profile-language"
          label={t("settings.profile.languageLabel")}
          value={language}
          onChange={(e) => changeLanguage(e.target.value as Language)}
          wrapperClassName="sm:max-w-md"
        >
          {LANGUAGES.map((option) => (
            <option key={option.code} value={option.code}>
              {communityCoverage(option.code) === null
                ? option.fullName
                : `${option.fullName} (${t("settings.communityLanguage", {
                    percent: communityCoverage(option.code),
                  })})`}
            </option>
          ))}
        </NativeSelect>
      </CardContent>
    </Card>
  );
}
