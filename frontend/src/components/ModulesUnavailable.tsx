import { useState } from "react";
import { useTranslation } from "react-i18next";
import { LayoutGrid, RefreshCw } from "lucide-react";
import { Button } from "./ui/Button";

/**
 * Shown in place of the whole shell when the organization's module list
 * cannot be read.
 *
 * A failed `GET /modules/my` used to stand in the default install's module
 * list: the module the organization had switched off came back into the
 * navigation, the five that were actually on vanished, and the switched-off
 * one's complete route rendered a data panel saying "error / try again"
 * about a 403 that would never clear. The list is the shell's map — without
 * it nothing can be named, so this screen says exactly that and offers the
 * one action that can change the outcome: asking again.
 */
export default function ModulesUnavailable({
  onRetry,
}: {
  onRetry: () => Promise<void>;
}) {
  const { t } = useTranslation("common");
  const [isRetrying, setIsRetrying] = useState(false);

  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center min-h-screen p-8 text-center bg-surface"
    >
      <div className="w-16 h-16 bg-amber-100 text-on-warning dark:bg-amber-900/30 dark:text-amber-300 rounded-full flex items-center justify-center mb-6">
        <LayoutGrid className="w-9 h-9" />
      </div>
      <h1 className="text-2xl font-semibold text-on mb-2">
        {t("errors.modulesUnavailableTitle")}
      </h1>
      <p className="text-on-secondary mb-8 max-w-md">
        {t("errors.modulesUnavailableBody")}
      </p>
      <Button
        onClick={async () => {
          setIsRetrying(true);
          try {
            await onRetry();
          } finally {
            setIsRetrying(false);
          }
        }}
        isLoading={isRetrying}
      >
        <RefreshCw size={18} className="mr-2" />
        {t("actions.retry")}
      </Button>
    </div>
  );
}
