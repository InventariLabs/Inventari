import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useFormGuard } from "@/hooks/useFormGuard";
import { usePageSave } from "@/hooks/usePageSave";
import { extractApiError } from "@/lib/errors";

interface SettingsSaveBarProps {
  /** Names the page in the "leave anyway?" question, already localized. */
  guardLabel: string;
  /** Said when a part's request is refused without a reason of its own. */
  failureMessage: string;
  successMessage: string;
}

/**
 * The page's one Save: it appears, stuck above the bottom nav, when any part
 * of the settings page holds an edit, and the page asks before it is left
 * with that edit unsaved (UI_GUIDELINES §11.9).
 */
export function SettingsSaveBar({
  guardLabel,
  failureMessage,
  successMessage,
}: SettingsSaveBarProps) {
  const { t } = useTranslation("common");
  const { dirty, saving, saveAll } = usePageSave();
  useFormGuard(dirty, guardLabel);

  if (!dirty) return null;

  const save = async () => {
    const failures = await saveAll();
    if (failures.length === 0) toast.success(successMessage);
    else
      for (const failure of failures)
        toast.error(extractApiError(failure, failureMessage));
  };

  return (
    <Card
      role="region"
      aria-label={t("settingsSave.region")}
      className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px)+0.5rem)] z-[var(--z-sticky)] flex flex-wrap items-center justify-between gap-3 p-4 shadow-lg md:bottom-2"
    >
      <p className="text-sm font-medium text-on">{t("settingsSave.unsaved")}</p>
      <Button onClick={() => void save()} isLoading={saving}>
        {t("actions.save")}
      </Button>
    </Card>
  );
}
