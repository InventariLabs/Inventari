import { useTranslation } from "react-i18next";
import { CloudOff, RefreshCw } from "lucide-react";
import { Button } from "./ui/Button";
import { useAuthStore } from "@/store/authStore";

/**
 * Shown in place of a protected screen when the session check got no answer.
 *
 * The shell used to read any failure of `/auth/me` as "nobody is signed in" and
 * send the reader to the sign-in form, where signing in failed for the same
 * reason. Naming the outage keeps the route, keeps the token, and gives the one
 * action that can change the outcome — asking again.
 */
export default function BackendUnavailable() {
  const { t } = useTranslation("common");
  const checkAuth = useAuthStore((s) => s.checkAuth);
  const isLoading = useAuthStore((s) => s.isLoading);

  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center min-h-screen p-8 text-center bg-surface"
    >
      <div className="w-16 h-16 bg-amber-100 text-on-warning dark:bg-amber-900/30 dark:text-amber-300 rounded-full flex items-center justify-center mb-6">
        <CloudOff className="w-9 h-9" />
      </div>
      <h1 className="text-2xl font-semibold text-on mb-2">
        {t("errors.backendUnavailableTitle")}
      </h1>
      <p className="text-on-secondary mb-8 max-w-md">
        {t("errors.backendUnavailableBody")}
      </p>
      <Button onClick={() => checkAuth()} isLoading={isLoading}>
        <RefreshCw size={18} className="mr-2" />
        {t("actions.retry")}
      </Button>
    </div>
  );
}
