import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useModules } from "@/contexts/ModulesContext";
import LoadingSpinner from "@/components/LoadingSpinner";
import { PageContainer } from "@/components/ui/PageContainer";
import { Button } from "@/components/ui/Button";

/**
 * Screens that browse or switch what the workspace is made of — the launcher
 * grid, the App Store — contradict the single-module view's promise of one module. While
 * the single-module view is on they say so and point at the way back, instead of offering
 * profile switches and activations that would silently end the focus.
 *
 * "Not focused" is an answer the server has to give. While the focus read is
 * pending the screen waits, and after it failed the screen says so and offers
 * a retry and the settings link: guessing "not focused" would put the App
 * Store's activations in front of a workspace that is, in fact, focused.
 */
export function FocusLockGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation("common");
  const { focusModule, focusStatus = "ready", refreshFocus } = useModules();

  if (focusStatus === "loading") return <LoadingSpinner fullScreen />;

  if (focusStatus === "failed") {
    return (
      <PageContainer className="py-12 space-y-3 text-center">
        <h1 className="text-xl font-semibold text-on">
          {t("focusLock.unknownTitle")}
        </h1>
        <p className="text-sm text-on-muted">{t("focusLock.unknownBody")}</p>
        <div className="flex items-center justify-center gap-4">
          {refreshFocus && (
            <Button variant="secondary" onClick={() => void refreshFocus()}>
              {t("focusLock.retry")}
            </Button>
          )}
          <Link
            to="/settings/my-modules"
            className="text-sm font-medium text-primary-600 hover:underline"
          >
            {t("focusLock.exit")}
          </Link>
        </div>
      </PageContainer>
    );
  }

  if (!focusModule) return <>{children}</>;

  return (
    <PageContainer className="py-12 space-y-3 text-center">
      <h1 className="text-xl font-semibold text-on">{t("focusLock.title")}</h1>
      <p className="text-sm text-on-muted">{t("focusLock.body")}</p>
      <Link
        to="/settings/my-modules"
        className="inline-block text-sm font-medium text-primary-600 hover:underline"
      >
        {t("focusLock.exit")}
      </Link>
    </PageContainer>
  );
}
