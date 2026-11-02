import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useModules } from "@/contexts/ModulesContext";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { ActionItem, FrontendModule } from "@/lib/moduleRegistry";
import { cn } from "@/lib/utils";

type Provider = {
  moduleName: string;
  hook: NonNullable<FrontendModule["useActionItems"]>;
};

function ModuleActionItemsCollector({
  moduleName,
  hook,
  onItems,
}: {
  moduleName: string;
  hook: Provider["hook"];
  onItems: (name: string, items: ActionItem[]) => void;
}) {
  const items = hook();
  useEffect(() => {
    onItems(moduleName, items);
  }, [moduleName, items, onItems]);
  return null;
}

function severityClasses(severity: ActionItem["severity"]): string {
  switch (severity) {
    case "error":
      return "bg-red-50 dark:bg-red-500/10 text-on-danger";
    case "warning":
      return "bg-amber-50 dark:bg-amber-500/10 text-on-warning";
    default:
      return "bg-primary-50 dark:bg-primary-500/10 text-primary-700 dark:text-primary-500";
  }
}

export function ActionItemsFeed() {
  const { t } = useTranslation("launcher");
  const tDyn = makeTDynamic(t);
  const { enabledModules } = useModules();
  const moduleLabels = useModuleLabels();
  const providers = moduleRegistry.getActionItemProviders(enabledModules);
  const [byModule, setByModule] = useState<Record<string, ActionItem[]>>({});

  // A module is named where the reader has already seen it named: the
  // launcher tile's own label first (shell modules like inventory have no
  // catalogue entry), the `modules.<name>.name` catalogue entry second — the
  // registry identifier itself never reaches the screen.
  function moduleName(technicalName: string): string {
    const tile = moduleRegistry.getModule(technicalName)?.launcher;
    if (tile) return tDyn(tile.displayName);
    return moduleLabels({
      name: technicalName,
      display_name: technicalName,
      description: "",
    }).name;
  }

  function collect(name: string, items: ActionItem[]) {
    setByModule((prev) => {
      const current = prev[name];
      if (
        current &&
        current.length === items.length &&
        current.every(
          (c, i) => c.id === items[i]?.id && c.count === items[i]?.count,
        )
      ) {
        return prev;
      }
      return { ...prev, [name]: items };
    });
  }

  const allItems = Object.entries(byModule).flatMap(([moduleName, items]) =>
    items.map((item) => ({ ...item, moduleName })),
  );
  // The subtitle and the row badges must agree: both count things to do, not
  // rows. A provider can pack several pending requests into one row, so
  // `allItems.length` understated the real total.
  const totalCount = allItems.reduce((sum, item) => sum + (item.count ?? 1), 0);

  if (providers.length === 0) {
    return null;
  }

  // The collectors are what discovers whether there is anything to show, so
  // they mount whether or not the card does — and outside it, since a card
  // that is not rendered cannot host them. They render nothing themselves.
  const collectors = providers.map((provider) => (
    <ModuleActionItemsCollector
      key={provider.moduleName}
      moduleName={provider.moduleName}
      hook={provider.hook}
      onItems={collect}
    />
  ));

  // Nothing to do is not news. The card used to hold its place with "All
  // caught up" inside it, which on first paint was a claim made before a
  // single provider had answered — `totalCount === 0` is the loading state as
  // much as the empty one, and the two are indistinguishable from here.
  if (totalCount === 0) {
    return <>{collectors}</>;
  }

  return (
    <Card className="p-5">
      {collectors}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-9 h-9 rounded-xl bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500 flex items-center justify-center">
          <Bell size={18} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-on leading-tight">
            {t("launcher.actionItems.title")}
          </h2>
          <p className="text-xs text-on-muted">
            {t("launcher.actionItems.subtitle", { count: totalCount })}
          </p>
        </div>
      </div>

      <ul className="space-y-2" data-testid="action-items-feed">
        {allItems.map((item) => {
          const Icon = item.icon;
          return (
            <li key={`${item.moduleName}-${item.id}`}>
              <Link
                to={item.linkTo}
                className={cn(
                  "flex items-center gap-3 rounded-xl border border-border bg-surface-card p-3",
                  "hover:bg-surface-raised hover:border-primary-300 active:scale-[0.99] transition-all",
                )}
              >
                <div
                  className={cn(
                    "shrink-0 w-9 h-9 rounded-lg flex items-center justify-center",
                    severityClasses(item.severity),
                  )}
                  aria-hidden="true"
                >
                  <Icon size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-on truncate">
                    {t(item.labelKey, item.labelValues)}
                  </p>
                  <p className="text-xs text-on-muted truncate uppercase tracking-wide">
                    {moduleName(item.moduleName)}
                  </p>
                </div>
                {typeof item.count === "number" && item.count > 0 && (
                  <span
                    className="shrink-0 text-xs font-medium text-on-secondary bg-surface-inset px-2 py-1 rounded-md"
                    data-testid="action-item-count"
                  >
                    {item.count}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
