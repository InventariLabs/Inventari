import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Plus, Store } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { usePartnerNames } from "@/hooks/usePartners";
import { usePartnerPicker } from "@/hooks/usePartnerPicker";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import {
  useCreatePricelist,
  useDeletePricelist,
  usePricelistForPartner,
  usePricelistForTemplate,
  useUpdatePricelist,
} from "../hooks/usePricelist";
import { useProductTemplatesCount } from "../hooks/useProductTemplatesCount";
import {
  documentsProductsApi,
  type CatalogueSearchResult,
} from "@/modules/warehouse/moduleApi";
import { SUPPLIER_ROLE_TYPES } from "@/module-sdk";
import type {
  PartnerPricelist,
  PartnerPricelistCreate,
  PartnerPricelistUpdate,
} from "../api/pricelist";
import { PricelistEntriesTable } from "../components/PricelistEntriesTable";
import { PricelistComparisonCard } from "../components/PricelistComparisonCard";
import {
  PricelistFormModal,
  emptyForm,
  type PricelistFormState,
} from "../components/PricelistFormModal";

export default function PricelistPage() {
  const { t } = useTranslation("purchase_orders");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("purchase_orders");
  const [partnerId, setPartnerId] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const orgCurrency = useDocumentCurrency(null);
  const blankForm = useCallback(
    () => ({ ...emptyForm(), currency: orgCurrency ?? "" }),
    [orgCurrency],
  );
  const [form, setForm] = useState<PricelistFormState>(blankForm);
  const [compareProduct, setCompareProduct] =
    useState<CatalogueSearchResult | null>(null);
  const compareProductId = compareProduct?.product_template_id ?? "";

  // the supplier set is filtered server-side through the
  // partners `types` param — reuse the canonical SUPPLIER_ROLE_TYPES instead
  // of a second local copy of the same set. The field searches the register
  // on the server as the reader types, so a register past one page is
  // reachable to its last supplier.
  const {
    options: supplierOptions,
    setSearch: setSupplierSearch,
    loading: suppliersLoading,
    error: suppliersErrorObject,
    retry: refetchSuppliers,
  } = usePartnerPicker(SUPPLIER_ROLE_TYPES, partnerId);
  const suppliersError = suppliersErrorObject != null;

  const {
    data: entries = [],
    isLoading,
    isError: entriesError,
    error: entriesErrorObject,
    refetch: refetchEntries,
  } = usePricelistForPartner(partnerId);
  const {
    data: compareEntries = [],
    isError: compareFailed,
    error: compareError,
    refetch: refetchCompare,
  } = usePricelistForTemplate(compareProductId);
  const { data: templateCount } = useProductTemplatesCount();
  // with an empty product catalog the form cannot be filled —
  // say so before it opens instead of letting the picker fail inside.
  // While the count is still loading the CTA stays enabled; only a
  // resolved zero gates it.
  const catalogEmpty = templateCount === 0;
  const createMutation = useCreatePricelist();
  const updateMutation = useUpdatePricelist();
  const deleteMutation = useDeletePricelist();

  const openCreate = useCallback(() => {
    setForm(blankForm());
    setFormOpen(true);
  }, [blankForm]);

  // Memoised because the shell stores the node: rebuilt on every render, the
  // effect below would set the header, re-render, and set it again.
  const headerActions = useMemo(
    () => (
      <Button
        variant="primary"
        leftIcon={<Plus size={16} />}
        onClick={openCreate}
        disabled={!partnerId || catalogEmpty}
      >
        {t("pricelist.addPrice")}
      </Button>
    ),
    [openCreate, partnerId, catalogEmpty, t],
  );

  useEffect(() => {
    setHeader({
      backTo: "/purchase-orders",
      title: t("pricelist.pageTitle"),
      subtitle: t("pricelist.pageSubtitle"),
      actions: canWrite ? headerActions : undefined,
    });
  }, [t, setHeader, headerActions, canWrite]);

  const openEdit = (entry: PartnerPricelist) => {
    setForm({
      id: entry.id,
      product: {
        product_template_id: entry.product_template_id,
        name: entry.product_name,
        sku: null,
        barcode: null,
        brand: null,
        uom_id: entry.uom_id,
        uom_symbol: null,
        image_url: null,
        is_stub: false,
      },
      unitPrice: String(entry.unit_price),
      currency: entry.currency,
      minQuantity: entry.min_quantity != null ? String(entry.min_quantity) : "",
      validFrom: entry.valid_from,
      validTo: entry.valid_to ?? "",
      notes: entry.notes ?? "",
    });
    setFormOpen(true);
  };

  /** The page's product search, shared by the form and the comparison card. */
  const searchProducts = useCallback(
    (q: string) => documentsProductsApi.productSearch(q),
    [],
  );

  const handleProductSelected = (product: CatalogueSearchResult) => {
    setForm({ ...form, product });
  };

  const handleCompareSelected = (product: CatalogueSearchResult) => {
    setCompareProduct(product);
  };

  const handleSave = async () => {
    if (!partnerId) return;
    try {
      if (!form.product && !form.id) {
        toast.error(t("pricelist.productRequired"));
        return;
      }
      const base = {
        unit_price: Number(form.unitPrice) || 0,
        currency: form.currency,
        min_quantity:
          form.minQuantity.trim() === "" ? null : Number(form.minQuantity),
        valid_from: form.validFrom,
        valid_to: form.validTo.trim() === "" ? null : form.validTo,
        notes: form.notes.trim() === "" ? null : form.notes,
      };
      if (form.id) {
        await updateMutation.mutateAsync({
          id: form.id,
          data: base as PartnerPricelistUpdate,
        });
        toast.success(t("pricelist.updated"));
      } else {
        const data: PartnerPricelistCreate = {
          ...base,
          partner_id: partnerId,
          product_template_id: form.product!.product_template_id,
          uom_id: form.product?.uom_id ?? null,
        };
        await createMutation.mutateAsync(data);
        toast.success(t("pricelist.created"));
      }
      setFormOpen(false);
    } catch (err) {
      // A refused duplicate is a 409 with its own code, so the reader gets a
      // sentence in their language and the form stays open on the entry they
      // were writing.
      if (extractApiErrorCode(err) === "PRICELIST_DUPLICATE") {
        toast.error(t("pricelist.duplicateRefused"));
        return;
      }
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  // `window.confirm` is the browser's dialog, not the product's — it
  // ignores the theme, the language of the buttons and the touch targets every
  // other confirmation here follows.
  const [deleteTarget, setDeleteTarget] = useState<PartnerPricelist | null>(
    null,
  );

  const handleDelete = async (entry: PartnerPricelist) => {
    setDeleteTarget(null);
    try {
      await deleteMutation.mutateAsync(entry.id);
      toast.success(t("pricelist.deleted"));
    } catch (err) {
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  const supplierNames = usePartnerNames(
    compareEntries.map((e) => e.partner_id),
  );

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="purchase_orders" />
      {/* The supplier is the page's scope, so it reads as a toolbar control
          rather than a panel of its own — a select alone in a card, with the
          action at the far edge, was a card holding two lonely things. */}
      <SearchableCombobox
        id="pricelist-supplier"
        label={t("pricelist.supplier")}
        // this field sat flush under the header subtitle and read as a
        // third line of it; give it its own breathing room.
        wrapperClassName="w-full sm:w-72 mt-2"
        value={partnerId}
        onChange={(v) => setPartnerId(v)}
        placeholder={t("pricelist.selectSupplier")}
        searchPlaceholder={t("form.searchPartner")}
        options={supplierOptions}
        onSearchChange={setSupplierSearch}
        loading={suppliersLoading}
      />

      {/* with a count endpoint the empty-catalog hint shows only
          when the catalog really is empty, next to the disabled CTA. */}
      {catalogEmpty && (
        <p className="text-xs text-on-muted">
          <Link
            to="/inventory/items"
            className="text-primary-600 hover:text-primary-700 hover:underline"
          >
            {t("productPicker.emptyCatalogHint")}
          </Link>
        </p>
      )}

      {suppliersError ? (
        // Inviting a choice from a list that failed to load is an
        // instruction the reader cannot carry out.
        <QueryFailure
          error={suppliersErrorObject}
          onRetry={() => refetchSuppliers()}
        />
      ) : partnerId && entriesError ? (
        <QueryFailure
          error={entriesErrorObject}
          onRetry={() => refetchEntries()}
        />
      ) : partnerId ? (
        <PricelistEntriesTable
          entries={entries}
          isLoading={isLoading}
          onEdit={openEdit}
          onDelete={setDeleteTarget}
          readOnly={!canWrite}
          onCreate={openCreate}
          catalogEmpty={catalogEmpty}
        />
      ) : (
        // Before, an unscoped page said "No prices yet" — an answer to a
        // question nobody had asked yet, next to a disabled Add button with
        // nothing to explain it.
        <EmptyState
          icon={Store}
          title={t("pricelist.noSupplierTitle")}
          description={t("pricelist.noSupplierDescription")}
        />
      )}

      {/* Price comparison across suppliers for one product */}
      {compareFailed && (
        <InlineQueryError
          error={compareError}
          onRetry={() => void refetchCompare()}
        />
      )}
      <PricelistComparisonCard
        compareProduct={compareProduct}
        entries={compareEntries}
        supplierNames={supplierNames}
        searchProducts={searchProducts}
        onSelect={handleCompareSelected}
        onClear={() => setCompareProduct(null)}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        variant="danger"
        title={t("pricelist.deleteConfirmTitle")}
        message={t("pricelist.deleteConfirm")}
        confirmLabel={t("common:actions.delete")}
        onConfirm={() => deleteTarget && void handleDelete(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />

      <PricelistFormModal
        open={formOpen}
        form={form}
        onChange={setForm}
        searchProducts={searchProducts}
        onProductSelected={handleProductSelected}
        onSave={handleSave}
        onClose={() => setFormOpen(false)}
        isSaving={createMutation.isPending || updateMutation.isPending}
      />
    </div>
  );
}
