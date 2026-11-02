import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Focus } from "lucide-react";
import { useModules } from "@/contexts/ModulesContext";
import { useHasPermission } from "@/hooks/useHasPermission";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";

/**
 * Header marker that says the workspace shows one module only and names it.
 * Showing one module belongs to the whole organization, so only an admin gets
 * a way back: the marker leads to Settings → My modules, where the toggle and
 * its confirmation live. Everyone else reads a label.
 *
 * Renders nothing outside that state and while the focus state is unknown —
 * "showing everything" is an answer the server has to give.
 */
export function FocusModeMarker() {
  const { t } = useTranslation("common");
  const { focusModule, focusStatus = "ready" } = useModules();
  const isAdmin = useHasPermission("admin:access");

  if (!focusModule || focusStatus !== "ready") return null;
  const displayName =
    moduleRegistry.getModule(focusModule)?.launcher?.displayName;
  if (!displayName) return null;

  const moduleName = makeTDynamic(t)(displayName);
  const className =
    "flex items-center gap-1.5 min-w-0 rounded-lg px-1.5 py-1 text-xs text-on-muted";
  // The module comes first and the sentence second, so a narrow header
  // truncates the sentence and never the one thing the marker names.
  const body = (note: string) => (
    <>
      <Focus
        size={14}
        className="hidden sm:block shrink-0"
        aria-hidden="true"
      />
      <span className="flex min-w-0 flex-col leading-tight">
        <span className="line-clamp-2 font-medium text-on">{moduleName}</span>
        <span className="truncate">{note}</span>
      </span>
    </>
  );

  if (isAdmin) {
    return (
      <Link
        to="/settings/my-modules"
        aria-label={t("focusMarker.label", { module: moduleName })}
        title={t("focusLock.exit")}
        className={`${className} min-h-11 md:min-h-0 hover:bg-surface-raised hover:text-on transition-colors`}
      >
        {body(t("focusMarker.mode"))}
      </Link>
    );
  }

  return (
    <span
      className={className}
      title={t("focusMarker.memberLabel", { module: moduleName })}
    >
      {body(t("focusMarker.memberMode"))}
    </span>
  );
}
