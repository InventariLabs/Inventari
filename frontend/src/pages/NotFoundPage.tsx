import { useMemo } from "react";
import { Link, useLocation } from "react-router-dom";
import { FileQuestion, PlugZap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { buttonVariants } from "@/components/ui/Button";
import { useModules } from "@/contexts/ModulesContext";
import { MODULE_PATHS } from "@/lib/moduleRegistry/modulePaths";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useModuleLabels } from "@/hooks/useModuleLabels";

/** Does a concrete path match a route pattern like `/labels/scan/:code`? */
function matchesRoute(pattern: string, path: string): boolean {
  const source = pattern
    .split("/")
    .map((segment) => (segment.startsWith(":") ? "[^/]+" : segment))
    .join("/");
  return new RegExp(`^${source}$`).test(path);
}

export default function NotFoundPage() {
  const location = useLocation();
  const { t } = useTranslation("common");
  const { enabledModules } = useModules();
  const moduleLabels = useModuleLabels();
  const isAdmin = useHasPermission("admin:access");

  // The table, not the registry: the registry only ever holds the modules
  // this organization has switched on, so asking it which module owns a path
  // could never name one that is off — the screen below was unreachable by
  // construction. The paths are read without importing a single module chunk.
  const isDisabledModule = useMemo(() => {
    const path = location.pathname;
    for (const [name, meta] of Object.entries(MODULE_PATHS)) {
      if (enabledModules.includes(name)) continue;
      if (meta.basePath && path.startsWith(meta.basePath)) {
        return name;
      }
      // A module without its own nav still owns its routes. Matching only on
      // `basePath` meant a disabled module with flat routes — the reference
      // `example_widgets` among them — answered with a plain 404, while its
      // neighbour got the proper "module is off" screen.
      if (meta.paths.some((routePath) => matchesRoute(routePath, path))) {
        return name;
      }
    }
    return null;
  }, [location.pathname, enabledModules]);

  if (isDisabledModule) {
    // `modules.<name>.name`, the single source of truth (docs/MODULE_NAMES.md).
    // Capitalising the identifier produced "Example_widgets", underscore and
    // all, in every language.
    const displayName = moduleLabels({
      name: isDisabledModule,
      display_name: isDisabledModule,
      description: "",
    }).name;
    return (
      <div className="flex flex-col items-center justify-center flex-1 h-full min-h-[50vh] text-center p-6">
        <div className="w-20 h-20 bg-amber-50 text-amber-500 rounded-full flex items-center justify-center mb-6">
          <PlugZap size={40} />
        </div>
        <h2 className="text-xl font-semibold text-on mb-2">
          {t("notFound.moduleNotEnabled")}
        </h2>
        <p className="text-on-secondary mb-2 max-w-xs mx-auto">
          {t("notFound.moduleNotEnabledDesc", { module: displayName })}
        </p>
        <p className="text-on-muted text-sm mb-8 max-w-xs mx-auto">
          {t("notFound.goToSettings")}
        </p>
        <div className="flex gap-3">
          {/* The store is admin-only; offering it to a member sent them to a
 screen that refuses them. */}
          {isAdmin && (
            <Link
              to="/apps"
              className="px-6 py-3 bg-primary-700 dark:bg-primary-800 text-white rounded-xl font-semibold hover:bg-primary-800 dark:hover:bg-primary-900 transition"
            >
              {t("notFound.openAppStore")}
            </Link>
          )}
          <Link
            to="/"
            className="px-6 py-3 bg-surface-raised text-on-secondary rounded-xl font-semibold hover:bg-surface-inset transition"
          >
            {t("notFound.dashboard")}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center flex-1 h-full min-h-[50vh] text-center p-6">
      <div className="w-20 h-20 bg-surface-raised text-on-muted rounded-full flex items-center justify-center mb-6">
        <FileQuestion size={40} />
      </div>
      <h2 className="text-xl font-semibold text-on mb-2">
        {t("notFound.title")}
      </h2>
      <p className="text-on-secondary mb-8 max-w-xs mx-auto">
        {t("notFound.description")}
      </p>
      <Link
        to="/"
        className={buttonVariants({ variant: "primary", size: "lg" })}
      >
        {t("notFound.goToDashboard")}
      </Link>
    </div>
  );
}
