import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

interface LoadingSpinnerProps {
  fullScreen?: boolean;
}

export default function LoadingSpinner({
  fullScreen = false,
}: LoadingSpinnerProps) {
  const { t } = useTranslation("common");
  if (fullScreen) {
    return (
      <div
        data-testid="app-loading"
        role="status"
        aria-live="polite"
        aria-label={t("a11y.loading")}
        className="flex items-center justify-center p-8 h-screen w-screen fixed top-0 left-0 bg-surface-card z-[var(--z-notification)]"
      >
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-accent-600" />
          <div className="font-semibold text-accent-600">{t("loadingApp")}</div>
        </div>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={t("a11y.loading")}
      className="flex items-center justify-center py-16"
    >
      <Loader2 className="w-8 h-8 animate-spin text-accent-600" />
    </div>
  );
}
