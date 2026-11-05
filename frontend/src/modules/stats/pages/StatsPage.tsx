import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useHasPermission } from "@/hooks/useHasPermission";
import { Link, Navigate, useLocation } from "react-router-dom";
import { LayoutGrid, Scale, Settings, Zap } from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { Card } from "@/components/ui/Card";
import { ScrollRow } from "@/components/ui/ScrollRow";
import RotationAnalysisCard from "../components/RotationAnalysisCard";
import SmartAlertsPanel from "../components/SmartAlertsPanel";
import ExpenseForecastChart from "../components/ExpenseForecastChart";
import PurchasePatternsGrid from "../components/PurchasePatternsGrid";
import StatsOverviewTab from "../components/StatsOverviewTab";
import StockReconciliationPanel from "../components/StockReconciliationPanel";
import type { StatsSectionFailure } from "../components/StatsOverviewTab";
import {
  useStatsHeadline,
  useStatsByStorage,
  useStatsByCategory,
  useExpiryForecast,
  useCostAnalysis,
  useRotationAnalysis,
  useSmartAlerts,
  useExpenseForecast,
  usePurchasePatterns,
  useStatsConfig,
  useReconciliation,
} from "@/modules/stats/hooks/useStats";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { useTracksExpiry } from "@/modules/shared/hooks/useTracksExpiry";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import { cn } from "@/lib/utils";

// Two tabs, one page: /inventory/stats and /inventory/stats/analytics.
// `to:` rather than `path:` — this is a list of links, and that is the shape
// the route-reachability gate reads. The inventory report tab is gone:
// grouping and whole-set sums live on the products list itself.
const STATS_TABS = [
  {
    to: "/inventory/stats",
    icon: LayoutGrid,
    labelKey: "stats:tabs.overview",
  },
  {
    to: "/inventory/stats/analytics",
    icon: Zap,
    labelKey: "stats:tabs.analytics",
  },
  // Not gated on the analytics toggle: this is a data-integrity report, not
  // a business metric, and it is where the scheduled drift warning sends the
  // reader. An organization with analytics switched off still gets the
  // warning, so the screen behind it has to exist.
  {
    to: "/inventory/stats/reconciliation",
    icon: Scale,
    labelKey: "stats:tabs.reconciliation",
  },
];

export default function StatsPage() {
  const { t } = useTranslation(["stats", "common"]);
  // Two routes, one page. Only the first is a nav item, and the header is no
  // longer lent to nested routes, so the page says what it is on both.
  const { setHeader } = useModulePageHeader();
  useEffect(() => {
    setHeader({ title: t("stats:title"), subtitle: t("stats:subtitle") });
  }, [setHeader, t]);
  const location = useLocation();
  const activeTab = useMemo<"overview" | "analytics" | "reconciliation">(() => {
    if (location.pathname.startsWith("/inventory/stats/analytics"))
      return "analytics";
    if (location.pathname.startsWith("/inventory/stats/reconciliation"))
      return "reconciliation";
    return "overview";
  }, [location.pathname]);
  const [showOverviewDetails, setShowOverviewDetails] = useState(false);
  // The settings screen behind the link below is administrator-only
  // (settingsAccess), so the link shows only to those it lets in.
  const isAdmin = useHasPermission("admin:access");

  // The analytics tab exists only where the organization has the
  // history to feed it — the profile presets the toggle (off for food_home),
  // an admin can flip it in module settings. Fail-open matches the backend
  // default, so a failed config fetch changes nothing for existing users.
  const { data: statsConfig, isLoading: isLoadingConfig } = useStatsConfig();
  const analyticsEnabled = statsConfig?.enable_analytics ?? true;
  // Same gate, other surface: the value signal on the overview is a business
  // metric, and the home profile presets it off. Read through the one hook
  // every other screen uses, so the figure stays hidden until the setting
  // has answered instead of showing for a moment and being taken back.
  const showInventoryValue = useShowInventoryValue();
  const showAnalytics = activeTab === "analytics" && analyticsEnabled;

  // The overview and the attention count the dashboard's heading reads too —
  // one endpoint, one number, whichever screen asks. They arrive as one unit:
  // one spinner until both are in, one failure card when either is not, and
  // one retry that asks both again (see `useStatsHeadline`). The module-data
  // setting travels with the count so both screens narrow to the same rows.
  const excludeModuleContexts = !useShowModuleData();
  const {
    data: headline,
    isLoading: isLoadingHeadline,
    isError: isHeadlineError,
    refetch: refetchHeadline,
  } = useStatsHeadline(excludeModuleContexts);

  // The overview's four supporting queries. Each one reports its own
  // failure: the tab used to render only when *every* one of them had
  // arrived, so one 500 blanked the page (see StatsSectionFailure).
  const {
    data: storageStats,
    isLoading: isLoadingStorage,
    error: storageError,
    refetch: refetchStorage,
  } = useStatsByStorage();
  const {
    data: categoryStats,
    isLoading: isLoadingCategory,
    error: categoryError,
    refetch: refetchCategory,
  } = useStatsByCategory();
  const {
    data: expiryForecast,
    isLoading: isLoadingForecast,
    error: expiryError,
    refetch: refetchExpiry,
  } = useExpiryForecast();
  const {
    data: costAnalysis,
    isLoading: isLoadingCost,
    error: costError,
    refetch: refetchCost,
  } = useCostAnalysis();

  // Analytics queries — gated on the module toggle too, so a visit that is
  // about to be redirected away does not fire four requests on the way out.
  const {
    data: rotationAnalysis,
    isLoading: isLoadingRotation,
    error: rotationError,
    refetch: refetchRotation,
  } = useRotationAnalysis(showAnalytics);

  const {
    data: smartAlerts,
    isLoading: isLoadingAlerts,
    error: alertsError,
    refetch: refetchAlerts,
  } = useSmartAlerts(showAnalytics);

  const {
    data: expenseForecast,
    isLoading: isLoadingForecastAdvanced,
    error: forecastError,
  } = useExpenseForecast(showAnalytics);

  const {
    data: purchasePatterns,
    isLoading: isLoadingPatterns,
    error: patternsError,
  } = usePurchasePatterns(showAnalytics);

  const {
    data: reconciliation,
    isLoading: isLoadingReconciliation,
    error: reconciliationError,
    refetch: refetchReconciliation,
  } = useReconciliation(activeTab === "reconciliation");

  const tracksExpiry = useTracksExpiry();

  const overviewFailures = useMemo<StatsSectionFailure[]>(
    () =>
      (
        [
          {
            key: "storage",
            message: t("errors.failedToLoadStorageDistribution"),
            error: storageError,
            onRetry: refetchStorage,
          },
          {
            key: "category",
            message: t("errors.failedToLoadCategoryDistribution"),
            error: categoryError,
            onRetry: refetchCategory,
          },
          {
            key: "expiry",
            message: t("errors.failedToLoadExpiryForecast"),
            error: expiryError,
            onRetry: refetchExpiry,
          },
          {
            key: "cost",
            message: t("errors.failedToLoadCostAnalysis"),
            error: costError,
            onRetry: refetchCost,
          },
        ] as const
      )
        .filter((section) => section.error)
        .map((section) => ({ ...section, onRetry: () => section.onRetry() })),
    [
      t,
      storageError,
      refetchStorage,
      categoryError,
      refetchCategory,
      expiryError,
      refetchExpiry,
      costError,
      refetchCost,
    ],
  );

  if (
    isLoadingHeadline ||
    isLoadingStorage ||
    isLoadingCategory ||
    isLoadingForecast ||
    isLoadingCost ||
    (activeTab === "analytics" && isLoadingConfig)
  ) {
    return <LoadingSpinner />;
  }

  // Route gate: the tab is hidden, and the route itself refuses — a deep
  // link lands back on the overview, not on a blank analytics pane.
  if (activeTab === "analytics" && !analyticsEnabled) {
    return <Navigate to="/inventory/stats" replace />;
  }

  // The headline numbers; a failed half leaves the health card unable to say
  // anything true, so neither is allowed to render a zero over it.
  if (isHeadlineError) {
    return <QueryError onRetry={refetchHeadline} />;
  }

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <nav className="flex items-center gap-0.5 border-b border-border -mx-3 md:-mx-4 lg:-mx-6 px-3 md:px-4 lg:px-6 -mt-1 pb-0">
        {/* The tabs scroll in a track of their own, with the edge fade that says
            there is more; the module settings link stands outside it, so a
            fourth tab can no longer push it off the screen unannounced. */}
        <ScrollRow className="flex min-w-0 items-center gap-0.5">
          {STATS_TABS.filter(
            (tab) =>
              tab.to !== "/inventory/stats/analytics" || analyticsEnabled,
          ).map((tab) => {
            const active =
              tab.to === "/inventory/stats"
                ? activeTab === "overview"
                : location.pathname.startsWith(tab.to);
            const Icon = tab.icon;
            return (
              <Link
                key={tab.to}
                to={tab.to}
                className={cn(
                  "flex items-center gap-2 px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap border-b-2 -mb-px",
                  active
                    ? "text-primary-700 border-primary-600"
                    : "text-on-secondary hover:text-on hover:bg-surface-raised/50 border-transparent",
                )}
              >
                <Icon size={16} />
                <span>{t(tab.labelKey)}</span>
              </Link>
            );
          })}
        </ScrollRow>
        {isAdmin && (
          <Link
            to="/settings/modules/stats"
            // Icon only on a phone: the words took 130 of 360 px and left the
            // tabs one and a half in view, the third one off the screen.
            aria-label={t("common:settings.moduleSettings.open")}
            title={t("common:settings.moduleSettings.open")}
            className="ml-auto inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-1 whitespace-nowrap text-sm text-on-secondary hover:text-on sm:h-auto sm:min-w-0 sm:justify-start sm:pb-2 sm:pl-2"
          >
            <Settings size={14} />
            <span className="hidden sm:inline">
              {t("common:settings.moduleSettings.open")}
            </span>
          </Link>
        )}
      </nav>

      {activeTab === "overview" && headline && (
        <StatsOverviewTab
          t={t}
          tracksExpiry={tracksExpiry}
          showInventoryValue={showInventoryValue}
          overview={headline.overview}
          attentionCounts={headline.counts}
          storageStats={storageStats || []}
          categoryStats={categoryStats || []}
          expiryForecast={expiryForecast || []}
          costAnalysis={costAnalysis}
          failures={overviewFailures}
          showDetails={showOverviewDetails}
          onToggleDetails={() => setShowOverviewDetails((prev) => !prev)}
        />
      )}

      {activeTab === "reconciliation" && (
        <div className="animate-in fade-in duration-500">
          {isLoadingReconciliation && (
            <div className="flex justify-center items-center py-16">
              <LoadingSpinner />
            </div>
          )}
          {reconciliationError && (
            <QueryError
              message={t("errors.failedToLoadReconciliation")}
              onRetry={() => refetchReconciliation()}
            />
          )}
          {reconciliation && <StockReconciliationPanel data={reconciliation} />}
        </div>
      )}

      {activeTab === "analytics" && (
        <div className="space-y-8 animate-in fade-in duration-500">
          {(isLoadingRotation ||
            isLoadingAlerts ||
            isLoadingForecastAdvanced ||
            isLoadingPatterns) && (
            <div className="flex justify-center items-center py-16">
              <LoadingSpinner />
            </div>
          )}

          {/* What failed, and the one action that can change it. These blocks
              used to name the failure and then leave the reader with nothing
              to press. */}
          {rotationError && (
            <QueryError
              message={t("errors.failedToLoadRotationAnalysis")}
              onRetry={() => refetchRotation()}
            />
          )}
          {alertsError && (
            <QueryError
              message={t("errors.failedToLoadAlerts")}
              onRetry={() => refetchAlerts()}
            />
          )}

          {smartAlerts &&
          smartAlerts.alerts &&
          smartAlerts.alerts.length > 0 ? (
            <SmartAlertsPanel alerts={smartAlerts} t={t} />
          ) : !isLoadingAlerts && !alertsError ? (
            <Card className="p-8 text-center border-border">
              <p className="text-on-secondary font-medium">
                {headline && headline.overview.total_items > 0
                  ? t("analytics.alerts.noAlerts")
                  : t("analytics.alerts.noData")}
              </p>
            </Card>
          ) : null}

          {rotationAnalysis ? (
            <RotationAnalysisCard
              data={rotationAnalysis}
              t={t}
              showInventoryValue={showInventoryValue}
            />
          ) : !isLoadingRotation && !rotationError ? (
            <Card className="p-8 text-center border-border">
              <p className="text-on-secondary font-medium">
                {t("analytics.rotation.noData")}
              </p>
            </Card>
          ) : null}

          {expenseForecast ? (
            <ExpenseForecastChart
              data={expenseForecast}
              t={t}
              showInventoryValue={showInventoryValue}
            />
          ) : !isLoadingForecastAdvanced && !forecastError ? (
            <Card className="p-8 text-center border-border">
              <p className="text-on-secondary font-medium">
                {t("analytics.forecast.noData")}
              </p>
            </Card>
          ) : null}

          {purchasePatterns ? (
            <PurchasePatternsGrid
              data={purchasePatterns}
              t={t}
              showInventoryValue={showInventoryValue}
            />
          ) : !isLoadingPatterns && !patternsError ? (
            <Card className="p-8 text-center border-border">
              <p className="text-on-secondary font-medium">
                {t("analytics.patterns.noPatterns")}
              </p>
            </Card>
          ) : null}
        </div>
      )}
    </div>
  );
}
