import { useTranslation } from "react-i18next";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { LocationCombobox } from "@/module-sdk";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { PartnerOption } from "@/hooks/usePartnerPicker";
import type { LocationPickerEmptyReason } from "@/modules/shared/lib/locationPickerOffer";
import type { ReceiveSource } from "@/modules/warehouse/components/receive/receiveDraft";
import type { DocumentType } from "@/modules/warehouse/types";

/** The three answers to where the goods come from, each saying what it means. */
function sourceOptions(t: (key: string) => string) {
  return [
    {
      id: "supplier",
      label: t("receive.source.supplier.label"),
      description: t("receive.source.supplier.description"),
    },
    {
      id: "return",
      label: t("receive.source.return.label"),
      description: t("receive.source.return.description"),
    },
    {
      id: "internal",
      label: t("receive.source.internal.label"),
      description: t("receive.source.internal.description"),
    },
  ];
}

interface Props {
  /** Who the goods come from: an internal receipt names no partner. */
  source: ReceiveSource;
  /** The document that answer writes, named under the choice. */
  docType: DocumentType;
  onSourceChange: (source: ReceiveSource) => void;
  partnersEnabled: boolean;
  partnerId: string;
  partnerOptions: PartnerOption[];
  onPartnerSearch: (query: string) => void;
  partnersLoading: boolean;
  partnersError: unknown;
  onRetryPartners: () => void;
  onPartnerChange: (id: string) => void;

  targetLocationId: string;
  onTargetChange: (id: string) => void;
  /** Set while the post was refused for want of a location. */
  targetError?: string;
  locationsEmptyReason: LocationPickerEmptyReason | null;
  locationsFailed: boolean;

  externalReference: string;
  onExternalReferenceChange: (value: string) => void;

  ordersLoading: boolean;
  ordersError: unknown;
  onRetryOrders: () => void;
  orderCount: number;
  chosenOrderId: string | null;
  chosenOrderNumber: string | null;
  chosenLineCount: number;
  orderOptions: Array<{ id: string; number: string; lineCount: number }>;
  onOrderChange: (id: string) => void;
}

/** Where the goods come from and where they go, with the order note. */
export function ReceiveHeaderFields({
  source,
  docType,
  onSourceChange,
  partnersEnabled,
  partnerId,
  partnerOptions,
  onPartnerSearch,
  partnersLoading,
  partnersError,
  onRetryPartners,
  onPartnerChange,
  targetLocationId,
  onTargetChange,
  targetError,
  locationsEmptyReason,
  locationsFailed,
  externalReference,
  onExternalReferenceChange,
  ordersLoading,
  ordersError,
  onRetryOrders,
  orderCount,
  chosenOrderId,
  chosenOrderNumber,
  chosenLineCount,
  orderOptions,
  onOrderChange,
}: Props) {
  const { t } = useTranslation("warehouse");
  // A phone does not list the order's lines under the fields: the receiving
  // session walks them, so the note does not point "below".
  const isPhone = useMediaQuery("(max-width: 639px)");

  const orderNote = (() => {
    // Only a supplier's delivery can be waiting on a purchase order.
    if (!partnerId || source !== "supplier") return null;
    if (ordersLoading) return t("receive.orderLooking");
    if (orderCount > 1) {
      const args = { count: orderCount, number: chosenOrderNumber ?? "" };
      return isPhone
        ? t("receive.ordersAwait", args)
        : t("receive.ordersWaiting", args);
    }
    if (chosenOrderNumber) {
      const args = { number: chosenOrderNumber, count: chosenLineCount };
      return isPhone
        ? t("receive.orderAwaits", args)
        : t("receive.orderExpected", args);
    }
    return t("receive.noOrderWaiting");
  })();

  return (
    <div className="space-y-4">
      <ChoiceGroup
        label={t("receive.source.label")}
        options={sourceOptions(t)}
        value={source}
        onChange={(id) => onSourceChange(id as ReceiveSource)}
        // A phone draws the three answers in one column, as the issue
        // screen's purpose choice does.
        layout={isPhone ? "grid2" : "grid"}
        required
      />
      <p className="text-xs text-on-muted">
        {t("receive.documentNote", { type: t(`types.${docType}`) })}
      </p>
      <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {partnersEnabled && source !== "internal" && (
          <SearchableCombobox
            label={t("receive.from")}
            options={partnerOptions}
            value={partnerId}
            onChange={onPartnerChange}
            onSearchChange={onPartnerSearch}
            loading={partnersLoading}
            placeholder={t(
              source === "return"
                ? "receive.customerPlaceholder"
                : "receive.fromPlaceholder",
            )}
            searchPlaceholder={t(
              source === "return"
                ? "receive.searchCustomers"
                : "receive.searchPartner",
            )}
            emptyMessage={t(
              source === "return"
                ? "form.noCustomersFound"
                : "receive.noSuppliers",
            )}
            title={t("receive.from")}
            required
          />
        )}
        <LocationCombobox
          id="receive-target-warehouse"
          label={t("receive.toWarehouse")}
          scope={{ purpose: "stock" }}
          value={targetLocationId}
          onChange={onTargetChange}
          error={targetError}
          placeholder={t("receive.warehousePlaceholder")}
          searchPlaceholder={t("receive.searchWarehouse")}
          emptyMessage={
            locationsEmptyReason === "nothing-to-offer"
              ? t("form.noOfferableLocations")
              : t("receive.noWarehouses")
          }
          title={t("receive.toWarehouse")}
          required
        />
        {source !== "internal" && (
          <Input
            label={t(
              source === "return"
                ? "receive.customerDocument"
                : "receive.supplierDocument",
            )}
            placeholder={t(
              source === "return"
                ? "receive.customerDocumentHint"
                : "receive.supplierDocumentHint",
            )}
            value={externalReference}
            onChange={(event) => onExternalReferenceChange(event.target.value)}
            wrapperClassName="sm:col-span-2 lg:col-span-2"
          />
        )}
      </div>

      {partnersError != null && (
        <InlineQueryError error={partnersError} onRetry={onRetryPartners} />
      )}
      {orderNote && (
        <div className="flex flex-wrap items-end gap-3">
          <p
            className={
              chosenOrderNumber
                ? "text-sm text-success-700"
                : "text-sm text-on-secondary"
            }
          >
            {orderNote}
          </p>
          {orderCount > 1 && (
            <NativeSelect
              label={t("receive.orderSelect")}
              labelClassName="sr-only"
              wrapperClassName="w-full sm:w-64"
              value={chosenOrderId ?? ""}
              onChange={(event) => onOrderChange(event.target.value)}
            >
              {orderOptions.map((order) => (
                <option key={order.id} value={order.id}>
                  {t("receive.orderOption", {
                    number: order.number,
                    count: order.lineCount,
                  })}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
      )}
      {ordersError != null && (
        <InlineQueryError error={ordersError} onRetry={onRetryOrders} />
      )}
      {locationsFailed && (
        <p role="alert" className="text-sm text-on-warning">
          {t("receive.warehouseFailed")}
        </p>
      )}
    </div>
  );
}
