import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight, Factory, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { formatDateRange } from "@/utils/formatters";
import { NeedsTable } from "@/modules/maker/components/NeedsTable";
import { OrderMissingButton } from "@/modules/maker/components/OrderMissingButton";
import { PlanCalendar } from "@/modules/maker/components/PlanCalendar";
import { ProductionCreateSheet } from "@/modules/maker/components/ProductionCreateSheet";
import { useProductionOrders } from "@/modules/maker/hooks/useProduction";
import {
  useNeeds,
  usePlanIntermediates,
} from "@/modules/maker/hooks/usePlanning";
import {
  planPeriod,
  shiftAnchor,
  type PlanView,
} from "@/modules/maker/lib/planPeriod";

/**
 * Planning several runs at once: the planned runs of a week or a month by
 * day — each marked covered, partly covered or short against the shelf the
 * runs before it leave — and, under them, one list of everything those runs
 * need, with what is on order and what is still missing.
 */
export default function ProductionPlanPage() {
  const { t } = useTranslation("maker");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("maker");
  const navigate = useNavigate();
  const [showCreate, setShowCreate] = useState(false);
  const [view, setView] = useState<PlanView>("week");
  const [anchor, setAnchor] = useState(() => new Date());
  const period = useMemo(() => planPeriod(view, anchor), [view, anchor]);

  useEffect(() => {
    setHeader({ title: t("planning.title"), subtitle: t("planning.subtitle") });
  }, [t, setHeader]);

  const runs = useProductionOrders({
    status: "DRAFT",
    sort: "oldest",
    planned_from: period.from,
    planned_to: period.to,
    limit: 200,
  });
  const scope = { date_from: period.from, date_to: period.to };
  const needs = useNeeds(scope);
  const planIntermediates = usePlanIntermediates(
    t("planning.intermediates.failed"),
  );

  const orders = (runs.data?.items ?? []).filter(
    (order) => order.production_date,
  );
  const rows = needs.data?.rows ?? [];
  const toMake = rows.filter(
    (r) => r.action === "make" && Number(r.missing) > 0,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <div
          role="group"
          aria-label={t("planning.view.label")}
          className="flex gap-1"
        >
          <Button
            size="sm"
            variant={view === "week" ? "primary" : "outline"}
            aria-pressed={view === "week"}
            onClick={() => setView("week")}
          >
            {t("planning.view.week")}
          </Button>
          <Button
            size="sm"
            variant={view === "month" ? "primary" : "outline"}
            aria-pressed={view === "month"}
            onClick={() => setView("month")}
          >
            {t("planning.view.month")}
          </Button>
        </div>
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("planning.previous")}
          onClick={() => setAnchor(shiftAnchor(view, anchor, -1))}
        >
          <ChevronLeft size={16} />
        </Button>
        <span
          className="text-sm font-medium text-on"
          data-testid="maker-plan-range"
        >
          {formatDateRange(period.from, period.to)}
        </span>
        <Button
          size="sm"
          variant="ghost"
          aria-label={t("planning.next")}
          onClick={() => setAnchor(shiftAnchor(view, anchor, 1))}
        >
          <ChevronRight size={16} />
        </Button>
      </div>

      {runs.isError ? (
        <QueryFailure error={runs.error} onRetry={() => runs.refetch()} />
      ) : (
        <PlanCalendar period={period} orders={orders} canWrite={canWrite} />
      )}

      <section className="space-y-3" aria-labelledby="maker-needs-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2
            id="maker-needs-heading"
            className="text-sm font-semibold text-on"
          >
            {t("planning.needs.title")}
          </h2>
          <div className="flex flex-wrap gap-2">
            {canWrite && toMake.length > 0 && (
              <Button
                size="sm"
                variant="outline"
                leftIcon={<Factory size={14} />}
                isLoading={planIntermediates.isPending}
                onClick={() =>
                  planIntermediates.mutate(scope, {
                    onSuccess: (result) =>
                      toast.success(
                        t("planning.intermediates.planned", {
                          count: result.runs.length,
                        }),
                      ),
                  })
                }
                data-testid="maker-plan-intermediates"
              >
                {t("planning.intermediates.button")}
              </Button>
            )}
            {rows.some((r) => r.action === "buy" && Number(r.missing) > 0) && (
              <OrderMissingButton scope={scope} />
            )}
          </div>
        </div>
        {needs.isError ? (
          <QueryFailure error={needs.error} onRetry={() => needs.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Factory}
            title={t("planning.needs.emptyTitle")}
            description={t("planning.needs.emptyDescription")}
            primaryAction={
              canWrite ? (
                <Button
                  leftIcon={<Plus size={16} />}
                  onClick={() => setShowCreate(true)}
                  data-testid="maker-plan-new-production"
                >
                  {t("productionList.newProduction")}
                </Button>
              ) : undefined
            }
          />
        ) : (
          needs.data && <NeedsTable view={needs.data} />
        )}
        {needs.data && needs.data.unmeasured.length > 0 && (
          <p className="text-xs text-on-secondary">
            {t("planning.needs.unmeasured", {
              names: needs.data.unmeasured.join(", "),
            })}
          </p>
        )}
      </section>
      <ProductionCreateSheet
        open={showCreate}
        startAs="planned"
        onClose={() => setShowCreate(false)}
        onSuccess={(orderId) => {
          setShowCreate(false);
          navigate(`/maker/production/${orderId}`);
        }}
      />
    </div>
  );
}
