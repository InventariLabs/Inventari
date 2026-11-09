import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { formatDecimalQty, formatQuantityLocale } from "@/utils/formatters";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ListControlBar, RowLabel } from "@/components/ui/ListControlBar";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { usePartnerPicker } from "@/hooks/usePartnerPicker";
import { SUPPLIER_ROLE_TYPES } from "@/module-sdk";
import { LocationCombobox } from "@/module-sdk";
import { useLocationsById } from "@/module-sdk";
import { extractApiError } from "@/lib/errors";
import {
  documentsProductsApi,
  type CatalogueSearchResult,
} from "@/modules/warehouse/moduleApi";
import {
  useReorderRules,
  useCreateReorderRule,
  useUpdateReorderRule,
  useDeleteReorderRule,
  useReplenishmentAlerts,
} from "../hooks/useReorderRules";
import { useProductTemplatesCount } from "../hooks/useProductTemplatesCount";
import type { ReorderRule } from "../api/reorder-rules";
import { ReorderAlertsCard } from "../components/ReorderAlertsCard";
import { ReorderRulesTable } from "../components/ReorderRulesTable";
import {
  ReorderRuleFormModal,
  emptyForm,
  type RuleFormState,
} from "../components/ReorderRuleFormModal";

export default function ReorderRulesPage() {
  const { t } = useTranslation("purchase_orders");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("purchase_orders");
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<RuleFormState>(emptyForm);
  const [search, setSearch] = useState("");
  const [locationFilter, setLocationFilter] = useState("");

  const openCreate = useCallback(() => {
    setForm({ ...emptyForm });
    setFormOpen(true);
  }, []);

  const { data: templateCount } = useProductTemplatesCount();
  // a rule needs a product, so an empty catalog makes the form
  // unfillable — disable the CTA and say why before it opens. While the
  // count is still loading the CTA stays enabled; only a resolved zero
  // gates it.
  const catalogEmpty = templateCount === 0;

  // Memoised because the shell stores the node: rebuilt on every render, the
  // effect below would set the header, re-render, and set it again.
  const headerActions = useMemo(
    () => (
      <Button
        variant="primary"
        leftIcon={<Plus size={16} />}
        onClick={openCreate}
        disabled={catalogEmpty}
      >
        {t("reorderRules.addRule")}
      </Button>
    ),
    [openCreate, t, catalogEmpty],
  );

  useEffect(() => {
    setHeader({
      backTo: "/purchase-orders",
      title: t("reorderRules.pageTitle"),
      subtitle: t("reorderRules.pageSubtitle"),
      actions: canWrite ? headerActions : undefined,
    });
  }, [t, setHeader, headerActions, canWrite]);

  const {
    data: rules = [],
    isLoading,
    isError: rulesFailed,
    error: rulesError,
    refetch: refetchRules,
  } = useReorderRules();
  const {
    data: alerts = [],
    isError: alertsFailed,
    error: alertsError,
    refetch: refetchAlerts,
  } = useReplenishmentAlerts();
  // Two answers behind one policy. What the filter and the rule form may
  // *offer* is a search of the places the policy allows (LocationCombobox,
  // which also names a place an open edit form holds). What a rule on screen
  // is *named* by is every place it points at: the table must say where a
  // rule points even when the policy keeps that location off the pickers —
  // so the places of the rules and alerts on screen are named by id, and the
  // organization's locations are never read whole.
  const { byId: placesById } = useLocationsById([
    ...rules.map((r) => r.location_id),
    ...alerts.map((a) => a.location_id),
  ]);
  // The preferred supplier is searched on the server as the reader types, so
  // a register past one page is reachable to its last supplier.
  const {
    options: partnerOptions,
    setSearch: setPartnerSearch,
    loading: partnersLoading,
    error: partnersError,
    retry: refetchPartners,
  } = usePartnerPicker(
    SUPPLIER_ROLE_TYPES,
    formOpen ? form.preferredPartnerId || undefined : undefined,
  );
  const partnersFailed = partnersError != null;
  // The API names each rule's supplier, so the list needs no read per partner.
  const partnerNames = useMemo(
    () =>
      new Map(
        rules.flatMap((r) =>
          r.preferred_partner_id && r.preferred_partner_name
            ? [[r.preferred_partner_id, r.preferred_partner_name] as const]
            : [],
        ),
      ),
    [rules],
  );
  const createMutation = useCreateReorderRule();
  const updateMutation = useUpdateReorderRule();
  const deleteMutation = useDeleteReorderRule();

  const alertByRule = useMemo(
    () => new Map(alerts.map((a) => [a.reorder_rule_id, a])),
    [alerts],
  );

  // Client-side filtering: product name search + location select.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rules.filter((rule) => {
      if (q && !rule.product_name.toLowerCase().includes(q)) return false;
      if (locationFilter && rule.location_id !== locationFilter) {
        return false;
      }
      return true;
    });
  }, [rules, search, locationFilter]);

  const locationName = (id: string) => placesById.get(id)?.name ?? id;
  const partnerName = (id: string | null | undefined) =>
    id ? (partnerNames.get(id) ?? id) : "—";

  const openEdit = (rule: ReorderRule) => {
    setForm({
      id: rule.id,
      product: {
        product_template_id: rule.product_template_id,
        // the API returns the product name; the form used to receive
        // the template id in the field named `name`, and the first caller
        // that displayed `form.product.name` in edit mode showed a UUID.
        name: rule.product_name,
        sku: null,
        barcode: null,
        brand: null,
        // the edit form needs the product's unit to keep showing it
        // beside the thresholds — the API now returns both (from the product
        // template), instead of dropping the unit on open.
        uom_id: rule.uom_id,
        uom_symbol: rule.uom_symbol,
        image_url: null,
        is_stub: false,
      },
      locationId: rule.location_id,
      // A number input takes a plain, point-decimal string and writes it in
      // the reader's own way. The wire's "2.000" went in as it came, and a
      // comma-decimal browser then showed a piece count with three decimals.
      minQuantity: formatDecimalQty(rule.min_quantity),
      maxQuantity: formatDecimalQty(rule.max_quantity),
      safetyStock: formatDecimalQty(rule.safety_stock),
      preferredPartnerId: rule.preferred_partner_id ?? "",
      notes: rule.notes ?? "",
    });
    setFormOpen(true);
  };

  const handleProductSelected = (product: CatalogueSearchResult) => {
    setForm({ ...form, product });
  };

  const searchProducts = useCallback(
    (q: string) => documentsProductsApi.productSearch(q),
    [],
  );

  const handleSave = async () => {
    try {
      if (!form.product && !form.id) {
        toast.error(t("reorderRules.productRequired"));
        return;
      }
      if (!form.locationId) {
        toast.error(t("reorderRules.locationRequired"));
        return;
      }
      const base = {
        min_quantity: Number(form.minQuantity) || 0,
        max_quantity: Number(form.maxQuantity) || 0,
        safety_stock: Number(form.safetyStock) || 0,
        preferred_partner_id:
          form.preferredPartnerId === "" ? null : form.preferredPartnerId,
        notes: form.notes.trim() === "" ? null : form.notes,
      };
      // The shelf answers alongside the rule: a save that wants more of
      // the product than the location holds still succeeds, and the
      // warning toast names the limit instead of the numbers silently
      // disagreeing.
      const saved = form.id
        ? await updateMutation.mutateAsync({ id: form.id, data: base })
        : await createMutation.mutateAsync({
            ...base,
            product_template_id: form.product!.product_template_id,
            location_id: form.locationId,
          });
      if (saved.over_capacity) {
        // Two numbers, each on its own side: the rule wants `max_quantity`,
        // the shelf holds `capacity_max_quantity`. Interpolating the shelf's
        // limit into "it wants {{max}}" read the warning backwards — a rule
        // asking for 300 on a shelf that holds 200 said "it wants 200",
        // which is the shelf's number in the rule's mouth. The documents
        // module has said it the right way round since it was written
        // ("wants {{reorder}} … holds ({{max}})").
        toast.warning(
          t("reorderRules.overCapacity", {
            max: formatQuantityLocale(String(saved.max_quantity)),
            capacity: formatQuantityLocale(saved.capacity_max_quantity ?? ""),
          }),
        );
      } else {
        toast.success(
          form.id ? t("reorderRules.updated") : t("reorderRules.created"),
        );
      }
      setFormOpen(false);
    } catch (err) {
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  // `window.confirm` is the browser's dialog, not the product's — it
  // ignores the theme, the language of the buttons and the touch targets every
  // other confirmation here follows.
  const [deleteTarget, setDeleteTarget] = useState<ReorderRule | null>(null);

  const handleDelete = async (rule: ReorderRule) => {
    setDeleteTarget(null);
    try {
      await deleteMutation.mutateAsync(rule.id);
      toast.success(t("reorderRules.deleted"));
    } catch (err) {
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="purchase_orders" />
      {/* One bar, not a bar beside a second row of its own controls: the
          search field stretches, the location filter sits at its far end, and
          the create action is where every other page in this module puts it —
          in the shell header. Before, the search kept its intrinsic width in a
          flex row and floated alone at the left. */}
      {/* The count and the search belong to a list. When the list could not
          be read they describe nothing — and "0 rules" beside "11 products
          below minimum stock" reads as a fact about the organization rather
          than as one half of the page having failed. */}
      {!rulesFailed && (
        <ListControlBar
          search={{
            value: search,
            onChange: setSearch,
            placeholder: t("reorderRules.searchPlaceholder"),
          }}
          resultCount={filtered.length}
          resultCountLabel={t("reorderRules.count", { count: rules.length })}
          primaryAction={
            <>
              <RowLabel>{t("reorderRules.location")}</RowLabel>
              <div className="w-52">
                <LocationCombobox
                  value={locationFilter}
                  onChange={setLocationFilter}
                  placeholder={t("reorderRules.allLocations")}
                  title={t("reorderRules.location")}
                  aria-label={t("reorderRules.location")}
                  clearable
                  clearLabel={t("reorderRules.allLocations")}
                />
              </div>
            </>
          }
        />
      )}

      {/* with a count endpoint the empty-catalog hint shows only
          when the catalog really is empty, next to the disabled CTA. */}
      {catalogEmpty && (
        <p className="text-xs text-on-muted">
          <Link
            to="/inventory/items"
            className="text-on-primary hover:underline"
          >
            {t("productPicker.emptyCatalogHint")}
          </Link>
        </p>
      )}

      {/* The alerts came back on their own request and are true whatever
          happened to the rules, so they stay. */}
      {alertsFailed && (
        <InlineQueryError
          error={alertsError}
          onRetry={() => void refetchAlerts()}
        />
      )}
      {partnersFailed && (
        <InlineQueryError
          error={partnersError}
          onRetry={() => void refetchPartners()}
        />
      )}
      {alerts.length > 0 && (
        <ReorderAlertsCard
          alerts={alerts}
          locationName={locationName}
          canWrite={canWrite}
        />
      )}

      {rulesFailed ? (
        <QueryFailure error={rulesError} onRetry={() => refetchRules()} />
      ) : (
        <ReorderRulesTable
          rules={filtered}
          isLoading={isLoading}
          alertByRule={alertByRule}
          locationName={locationName}
          partnerName={partnerName}
          onEdit={openEdit}
          onDelete={setDeleteTarget}
          readOnly={!canWrite}
          isFiltered={rules.length > 0}
          onCreate={openCreate}
          catalogEmpty={catalogEmpty}
        />
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        variant="danger"
        title={t("reorderRules.deleteConfirmTitle")}
        message={t("reorderRules.deleteConfirm")}
        confirmLabel={t("common:actions.delete")}
        onConfirm={() => deleteTarget && void handleDelete(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />

      <ReorderRuleFormModal
        open={formOpen}
        form={form}
        onChange={setForm}
        searchProducts={searchProducts}
        onProductSelected={handleProductSelected}
        partnerOptions={partnerOptions}
        onPartnerSearch={setPartnerSearch}
        partnersLoading={partnersLoading}
        onSave={handleSave}
        onClose={() => setFormOpen(false)}
        isSaving={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}
