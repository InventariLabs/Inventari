import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { ProductCombobox } from "@/components/ui/ProductCombobox";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  type SheetZTier,
} from "@/components/ui/Sheet";
import { QueryFailure } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useConfirm } from "@/hooks/useConfirm";
import { useFormGuard } from "@/hooks/useFormGuard";
import { queryKeys } from "@/hooks/queries/keys";
import { storagesApi } from "@/lib/api/storages";
import { invalidation } from "@/lib/api/invalidation";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";
import {
  putawayCapacityApi,
  type PutawayCapacityEntry,
  type PutawayLocationSetting,
} from "@/modules/warehouse/api/putaway";
import {
  documentsProductsApi,
  type CatalogueSearchResult,
} from "@/modules/warehouse/api/documents_products";

export interface ShelfSettingsTarget {
  id: string;
  name: string;
  sequence?: number | null;
  full_path?: string | null;
}

interface ShelfSettingsSheetProps {
  /** The shelf whose settings the panel edits. */
  location: ShelfSettingsTarget;
  /** This account may change the mix flag and the limits (`warehouse:write`). */
  canWrite: boolean;
  /**
   * This account may change the walk order (`locations:write`).
   *
   * The walk order is a property of the storage register, while the mix and
   * the limits belong to this module; each control follows its own endpoint's
   * permission rather than the screen's.
   */
  canWriteStorages: boolean;
  /**
   * Layer for a panel that opens over another surface — the rule editor
   * (UI_GUIDELINES §4.1: a nested modal takes `--z-modal-nested`). A panel
   * opened from a page keeps the standard tier.
   */
  zIndex?: SheetZTier;
  onClose: () => void;
}

/**
 * The shelf-settings panel: walk order, product mixing and the per-product
 * limits, saved together by one button.
 *
 * Nothing saves on change here — the capacity card this replaces saved the
 * mix switch on change and the limit on a button, which is two save models
 * on one card and neither of them visible. The panel holds the edit until
 * "Save changes", and says so while there is one.
 */
export function ShelfSettingsSheet({
  location,
  canWrite,
  canWriteStorages,
  zIndex = "modal",
  onClose,
}: ShelfSettingsSheetProps) {
  const { t } = useTranslation(["warehouse", "locations"]);
  const { confirm, confirmDialogProps } = useConfirm();
  // The panel's unsaved work lives in the form; the close paths belong to the
  // sheet (Escape, the backdrop, the header's X), so the form reports the
  // state up rather than each path learning to ask.
  const dirtyRef = useRef(false);
  const onDirtyChange = useCallback((value: boolean) => {
    dirtyRef.current = value;
  }, []);

  const requestClose = async () => {
    if (
      dirtyRef.current &&
      !(await confirm({
        title: t("putaway.locations.panel.discardTitle"),
        message: t("putaway.locations.panel.discardMessage"),
        variant: "danger",
        confirmLabel: t("putaway.locations.panel.discard"),
      }))
    ) {
      return;
    }
    onClose();
  };

  const {
    data: entries,
    isError: entriesError,
    error: entriesFailure,
    refetch: refetchEntries,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacity(location.id),
    queryFn: () => putawayCapacityApi.list({ location_id: location.id }),
  });

  const {
    data: setting,
    isError: settingError,
    error: settingFailure,
    refetch: refetchSetting,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacitySetting(location.id),
    queryFn: () => putawayCapacityApi.getSetting(location.id),
  });

  return (
    <Sheet
      open
      onClose={() => void requestClose()}
      maxWidth="xl"
      zIndex={zIndex}
      aria-label={t("putaway.locations.panel.title")}
    >
      <SheetHeader
        title={t("putaway.locations.panel.title")}
        onClose={() => void requestClose()}
      >
        <span className="hidden truncate text-sm text-on-muted sm:block">
          {location.full_path ?? location.name}
        </span>
      </SheetHeader>
      {entriesError || settingError ? (
        <SheetBody>
          <QueryFailure
            error={entriesFailure ?? settingFailure}
            message={t("errors.loadShelfSettingsFailed")}
            onRetry={() => {
              void refetchEntries();
              void refetchSetting();
            }}
          />
        </SheetBody>
      ) : entries === undefined || setting === undefined ? (
        <SheetBody>
          <div className="p-6">
            <LoadingSpinner />
          </div>
        </SheetBody>
      ) : (
        <ShelfSettingsForm
          key={location.id}
          location={location}
          entries={entries}
          setting={setting}
          canWrite={canWrite}
          canWriteStorages={canWriteStorages}
          onSaved={onClose}
          onRequestClose={() => void requestClose()}
          onDirtyChange={onDirtyChange}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </Sheet>
  );
}

interface LimitDraft {
  /** A stable key: the entry id, or `new-<n>` for a row not saved yet. */
  key: string;
  entryId: string | null;
  productTemplateId: string;
  productName: string;
  unitSymbol: string | null;
  maxQuantity: string;
  /** What the server holds now, to know which rows changed. */
  originalQuantity: string;
  removed: boolean;
}

function valueOf(value: string | number | null | undefined): string {
  return value == null ? "" : String(value);
}

function toDraft(entry: PutawayCapacityEntry, t: TranslateFn): LimitDraft {
  return {
    key: entry.id,
    entryId: entry.id,
    productTemplateId: entry.product_template_id,
    productName: entry.product_template_name ?? "—",
    unitSymbol: unitLabel(t, entry.product_unit_symbol) || null,
    maxQuantity: valueOf(entry.max_quantity),
    originalQuantity: valueOf(entry.max_quantity),
    removed: false,
  };
}

/**
 * What a limit still open in the add row is missing, with no entry when the
 * row is empty. The row is part of the panel's work, so Save checks it like
 * a limit already in the list instead of closing over it.
 */
function pendingLimitProblems(
  product: CatalogueSearchResult | null,
  quantity: string,
  limits: LimitDraft[],
  t: TranslateFn,
): Record<string, string> {
  if (product === null && quantity.trim() === "") return {};
  const next: Record<string, string> = {};
  if (!product) {
    next.product = t("putaway.locations.panel.productMissing");
  } else if (
    limits.some(
      (limit) =>
        !limit.removed &&
        limit.productTemplateId === product.product_template_id,
    )
  ) {
    next.product = t("putaway.locations.panel.duplicate");
  }
  if (!quantity.trim()) {
    next.quantity = t("putaway.locations.panel.quantityMissing");
  } else if (!(Number(quantity) > 0)) {
    next.quantity = t("putaway.locations.panel.quantityInvalid");
  }
  return next;
}

/**
 * What the panel still has to say before a Save: the walk order, every limit
 * in the list, and the limit left in the add row.
 */
function shelfSettingsProblems(
  sequence: string,
  product: CatalogueSearchResult | null,
  quantity: string,
  limits: LimitDraft[],
  t: TranslateFn,
): Record<string, string> {
  const next: Record<string, string> = {};
  const trimmed = sequence.trim();
  if (trimmed !== "") {
    const number = Number(trimmed);
    if (!Number.isInteger(number) || number < 0) {
      next.sequence = t("putaway.locations.panel.walkOrderError");
    }
  }
  Object.assign(next, pendingLimitProblems(product, quantity, limits, t));
  for (const limit of limits) {
    if (limit.removed) continue;
    if (!limit.maxQuantity.trim()) {
      next[`quantity-${limit.key}`] = t(
        "putaway.locations.panel.quantityMissing",
      );
    } else if (!(Number(limit.maxQuantity) > 0)) {
      next[`quantity-${limit.key}`] = t(
        "putaway.locations.panel.quantityInvalid",
      );
    }
  }
  return next;
}

/** One Save of the panel, split into the requests it sends. */
interface ShelfSettingsWrite {
  locationId: string;
  /** The walk order to write; absent when it did not change. */
  sequence?: number | null;
  /** The mixing choice to write; null when it did not change. */
  singleProduct: boolean | null;
  limits: LimitDraft[];
  /** The limit still open in the add row, written with the same Save. */
  pending: { productTemplateId: string; maxQuantity: string } | null;
}

interface ShelfSettingsWriteResult {
  /** At least one request landed, so the table and the caches are stale. */
  savedAnything: boolean;
  /** What the server refused, to keep that work in the panel. */
  failures: unknown[];
  writtenEntries: PutawayCapacityEntry[];
  sequenceSaved: boolean;
  singleProductSaved: boolean;
  removedKeys: string[];
  updatedLimits: { key: string; entry: PutawayCapacityEntry }[];
  createdLimits: { key: string; entry: PutawayCapacityEntry }[];
  pendingEntry: PutawayCapacityEntry | null;
}

/**
 * Write the panel's changes one request at a time and report what landed.
 *
 * One Save spans several endpoints and the server takes them one at a time,
 * so a refusal halfway cannot take back what came before it. Reporting each
 * success instead of failing the whole batch is what lets the same Save
 * finish after the person corrects the refused row: the caller folds the
 * successes into its drafts, and the next attempt sends only what is left.
 */
async function writeShelfSettings(
  write: ShelfSettingsWrite,
): Promise<ShelfSettingsWriteResult> {
  const result: ShelfSettingsWriteResult = {
    savedAnything: false,
    failures: [],
    writtenEntries: [],
    sequenceSaved: false,
    singleProductSaved: false,
    removedKeys: [],
    updatedLimits: [],
    createdLimits: [],
    pendingEntry: null,
  };

  const step = async (send: () => Promise<void>) => {
    try {
      await send();
      result.savedAnything = true;
    } catch (error) {
      result.failures.push(error);
    }
  };

  if (write.sequence !== undefined) {
    const sequence = write.sequence;
    await step(async () => {
      await storagesApi.update(write.locationId, { sequence });
      result.sequenceSaved = true;
    });
  }

  if (write.singleProduct !== null) {
    const singleProduct = write.singleProduct;
    await step(async () => {
      await putawayCapacityApi.putSetting(write.locationId, singleProduct);
      result.singleProductSaved = true;
    });
  }

  for (const limit of write.limits) {
    if (!limit.removed || limit.entryId === null) continue;
    const entryId = limit.entryId;
    await step(async () => {
      await putawayCapacityApi.remove(entryId);
      result.removedKeys.push(limit.key);
    });
  }

  for (const limit of write.limits) {
    if (
      limit.removed ||
      limit.entryId === null ||
      limit.maxQuantity === limit.originalQuantity
    ) {
      continue;
    }
    const entryId = limit.entryId;
    await step(async () => {
      const entry = await putawayCapacityApi.update(entryId, limit.maxQuantity);
      result.writtenEntries.push(entry);
      result.updatedLimits.push({ key: limit.key, entry });
    });
  }

  for (const limit of write.limits) {
    if (limit.removed || limit.entryId !== null) continue;
    await step(async () => {
      const entry = await putawayCapacityApi.create({
        location_id: write.locationId,
        product_template_id: limit.productTemplateId,
        max_quantity: limit.maxQuantity,
      });
      result.writtenEntries.push(entry);
      result.createdLimits.push({ key: limit.key, entry });
    });
  }

  if (write.pending) {
    const pending = write.pending;
    await step(async () => {
      const entry = await putawayCapacityApi.create({
        location_id: write.locationId,
        product_template_id: pending.productTemplateId,
        max_quantity: pending.maxQuantity,
      });
      result.writtenEntries.push(entry);
      result.pendingEntry = entry;
    });
  }

  return result;
}

function ShelfSettingsForm({
  location,
  entries,
  setting,
  canWrite,
  canWriteStorages,
  onSaved,
  onRequestClose,
  onDirtyChange,
}: {
  location: ShelfSettingsTarget;
  entries: PutawayCapacityEntry[];
  setting: PutawayLocationSetting;
  canWrite: boolean;
  canWriteStorages: boolean;
  onSaved: () => void;
  onRequestClose: () => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(["warehouse", "locations"]);
  const queryClient = useQueryClient();

  const initialSequence = valueOf(location.sequence);
  const [sequence, setSequence] = useState(initialSequence);
  // What the server holds, kept beside the draft: a Save that the server
  // refuses halfway leaves the steps before it persisted, so the panel
  // remembers them and the next Save retries only what did not land.
  const [savedSequence, setSavedSequence] = useState(initialSequence);
  const [singleProduct, setSingleProduct] = useState(setting.single_product);
  const [savedSingleProduct, setSavedSingleProduct] = useState(
    setting.single_product,
  );
  const [limits, setLimits] = useState<LimitDraft[]>(() =>
    entries.map((entry) => toDraft(entry, t)),
  );

  const [product, setProduct] = useState<CatalogueSearchResult | null>(null);
  const [quantity, setQuantity] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [nextNewKey, setNextNewKey] = useState(0);

  const dirty =
    sequence !== savedSequence ||
    singleProduct !== savedSingleProduct ||
    // Work still in the add row is work: closing the panel has to ask
    // about it, and Save below has to take it, not drop it.
    product !== null ||
    quantity.trim() !== "" ||
    limits.some(
      (limit) =>
        limit.removed ||
        limit.entryId === null ||
        limit.maxQuantity !== limit.originalQuantity,
    );

  useFormGuard(
    dirty,
    t("putaway.locations.panel.formLabel", {
      name: location.name,
    }),
  );

  // The sheet owns the close question; this only says whether there is work
  // to ask about. Clearing on the way out keeps a saved or discarded shelf
  // from arming the next open.
  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const updateLimit = (key: string, maxQuantity: string) => {
    setLimits((current) =>
      current.map((limit) =>
        limit.key === key ? { ...limit, maxQuantity } : limit,
      ),
    );
    setErrors((current) => {
      const next = { ...current };
      delete next[`quantity-${key}`];
      return next;
    });
  };

  const removeLimit = (key: string) => {
    setLimits((current) =>
      current.map((limit) =>
        limit.key === key ? { ...limit, removed: true } : limit,
      ),
    );
  };

  const addLimit = () => {
    const next: Record<string, string> = {};
    if (!product) {
      next.product = t("putaway.locations.panel.productMissing");
    } else if (
      limits.some(
        (limit) =>
          !limit.removed &&
          limit.productTemplateId === product.product_template_id,
      )
    ) {
      next.product = t("putaway.locations.panel.duplicate");
    }
    if (!quantity.trim()) {
      next.quantity = t("putaway.locations.panel.quantityMissing");
    } else if (!(Number(quantity) > 0)) {
      next.quantity = t("putaway.locations.panel.quantityInvalid");
    }
    setErrors(next);
    if (Object.keys(next).length > 0 || !product) return;

    const key = `new-${nextNewKey}`;
    setNextNewKey((current) => current + 1);
    setLimits((current) => [
      ...current,
      {
        key,
        entryId: null,
        productTemplateId: product.product_template_id,
        productName: product.name,
        unitSymbol: unitLabel(t, product.uom_symbol) || null,
        maxQuantity: quantity,
        originalQuantity: "",
        removed: false,
      },
    ]);
    setProduct(null);
    setQuantity("");
  };

  const save = async () => {
    const problems = shelfSettingsProblems(
      sequence,
      product,
      quantity,
      limits,
      t,
    );
    setErrors(problems);
    if (Object.keys(problems).length > 0) return;

    setIsSaving(true);
    try {
      // One Save over several endpoints: see writeShelfSettings for why a
      // refused step must not send the steps beside it again.
      // `undefined` keeps the walk order as it is; `null` clears it.
      let nextSequence: number | null | undefined;
      if (canWriteStorages && sequence !== savedSequence) {
        const trimmed = sequence.trim();
        nextSequence = trimmed === "" ? null : Number(trimmed);
      }
      const result = await writeShelfSettings({
        locationId: location.id,
        sequence: nextSequence,
        singleProduct:
          canWrite && singleProduct !== savedSingleProduct
            ? singleProduct
            : null,
        limits: canWrite ? limits : [],
        pending:
          canWrite && product
            ? {
                productTemplateId: product.product_template_id,
                maxQuantity: quantity.trim(),
              }
            : null,
      });

      if (result.sequenceSaved) setSavedSequence(sequence);
      if (result.singleProductSaved) setSavedSingleProduct(singleProduct);

      if (
        result.removedKeys.length > 0 ||
        result.updatedLimits.length > 0 ||
        result.createdLimits.length > 0
      ) {
        const removed = new Set(result.removedKeys);
        const written = new Map(
          [...result.updatedLimits, ...result.createdLimits].map(
            ({ key, entry }) => [key, entry],
          ),
        );
        setLimits((current) =>
          current
            .filter((row) => !removed.has(row.key))
            .map((row) => {
              const entry = written.get(row.key);
              return entry
                ? {
                    ...row,
                    entryId: entry.id,
                    maxQuantity: valueOf(entry.max_quantity),
                    originalQuantity: valueOf(entry.max_quantity),
                  }
                : row;
            }),
        );
      }

      if (result.pendingEntry) {
        const pendingEntry = result.pendingEntry;
        setLimits((current) => [...current, toDraft(pendingEntry, t)]);
        setProduct(null);
        setQuantity("");
      }

      // The replenishment side of the same pair may now ask for more than
      // the shelf holds; the old card said so when this was saved, and the
      // warning still belongs to the moment the limit is set.
      const over = result.writtenEntries.find(
        (entry) => entry.reorder_over_capacity === true,
      );
      if (over) {
        const inUnit = (value: string | null | undefined) =>
          formatQuantityLocalized(t, value, over.product_unit_symbol);
        toast.warning(
          t("putaway.capacity.reorderWarning", {
            product: over.product_template_name ?? "",
            max: inUnit(over.max_quantity),
            reorder: inUnit(over.reorder_max_quantity),
          }),
        );
      }

      // Refresh for what did land even when a later step was refused: the
      // table is the record of the server, and it cannot keep showing the
      // state from before a save that changed half of it.
      if (result.savedAnything) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.documents.putawayCapacityAll,
        });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.documents.putawayCapacitySettings,
        });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.documents.putawayCapacitySetting(location.id),
        });
        void queryClient.invalidateQueries({
          queryKey: queryKeys.documents.putawayOccupancyAll,
        });
        // The table reads `storages.tree`; the flat list is a separate key, so
        // invalidating only that one left a new walk order on the server and
        // the old one on the screen. The shared helper clears both.
        invalidation.storages(queryClient);
      }

      if (result.failures.length > 0) {
        // The panel stays open with the refused work still in its fields, so
        // the next Save sends just that and finishes the panel.
        toast.error(
          extractApiError(
            result.failures[0],
            t("putaway.locations.panel.saveError"),
          ),
        );
      } else {
        toast.success(t("putaway.locations.panel.saved"));
        onSaved();
      }
    } finally {
      setIsSaving(false);
    }
  };

  const visibleLimits = limits.filter((limit) => !limit.removed);

  return (
    <>
      <SheetBody>
        <div className="space-y-6 px-4 py-5 sm:px-6">
          <MixingSection
            sequence={sequence}
            onSequenceChange={(value) => {
              setSequence(value);
              setErrors((current) => {
                const next = { ...current };
                delete next.sequence;
                return next;
              });
            }}
            sequenceError={errors.sequence}
            singleProduct={singleProduct}
            onSingleProductChange={setSingleProduct}
            canWrite={canWrite}
            canWriteStorages={canWriteStorages}
          />

          <LimitsEditor
            limits={visibleLimits}
            errors={errors}
            canWrite={canWrite}
            product={product}
            quantity={quantity}
            onProductSelect={(selected) => {
              setProduct(selected);
              setErrors((current) => {
                const next = { ...current };
                delete next.product;
                return next;
              });
            }}
            onProductClear={() => setProduct(null)}
            onQuantityChange={(value) => {
              setQuantity(value);
              setErrors((current) => {
                const next = { ...current };
                delete next.quantity;
                return next;
              });
            }}
            onUpdateLimit={updateLimit}
            onRemoveLimit={removeLimit}
            onAdd={addLimit}
          />
        </div>
      </SheetBody>

      <SheetFooter>
        <SheetActions>
          {dirty && (
            <span className="mr-auto text-xs font-medium text-amber-700">
              {t("putaway.locations.panel.unsaved")}
            </span>
          )}
          <Button variant="outline" onClick={onRequestClose}>
            {t("common:actions.cancel")}
          </Button>
          {(canWrite || canWriteStorages) && (
            <Button onClick={() => void save()} disabled={isSaving}>
              {t("putaway.locations.panel.save")}
            </Button>
          )}
        </SheetActions>
      </SheetFooter>
    </>
  );
}

function MixingSection({
  sequence,
  onSequenceChange,
  sequenceError,
  singleProduct,
  onSingleProductChange,
  canWrite,
  canWriteStorages,
}: {
  sequence: string;
  onSequenceChange: (value: string) => void;
  sequenceError?: string;
  singleProduct: boolean;
  onSingleProductChange: (singleProduct: boolean) => void;
  canWrite: boolean;
  canWriteStorages: boolean;
}) {
  const { t } = useTranslation(["warehouse", "locations"]);
  const mixingOptions = [
    {
      id: "mixed",
      label: t("putaway.locations.mixing.mixed"),
      description: t("putaway.locations.panel.mixedDescription"),
    },
    {
      id: "single",
      label: t("putaway.locations.mixing.single"),
      description: t("putaway.locations.panel.singleDescription"),
    },
  ];
  return (
    <>
      <section className="space-y-2">
        <Input
          id="shelf-settings-sequence"
          label={t("locations:edit.sequenceLabel")}
          type="number"
          inputMode="numeric"
          min={0}
          step={1}
          value={sequence}
          onChange={(e) => onSequenceChange(e.target.value)}
          description={t("locations:edit.sequenceHint")}
          error={sequenceError}
          disabled={!canWriteStorages}
        />
      </section>

      <section className="space-y-2">
        {canWrite ? (
          <ChoiceGroup
            label={t("putaway.locations.panel.mixing")}
            hint={t("putaway.locations.panel.mixingHint")}
            options={mixingOptions}
            value={singleProduct ? "single" : "mixed"}
            onChange={(id) => onSingleProductChange(id === "single")}
            layout="grid2"
          />
        ) : (
          <div>
            <p className="text-xs font-medium uppercase text-on-muted tracking-wide ml-1">
              {t("putaway.locations.panel.mixing")}
            </p>
            <p className="mt-1 text-sm text-on">
              {singleProduct
                ? t("putaway.locations.mixing.single")
                : t("putaway.locations.mixing.mixed")}
            </p>
          </div>
        )}
      </section>
    </>
  );
}

function LimitsEditor({
  limits,
  errors,
  canWrite,
  product,
  quantity,
  onProductSelect,
  onProductClear,
  onQuantityChange,
  onUpdateLimit,
  onRemoveLimit,
  onAdd,
}: {
  limits: LimitDraft[];
  errors: Record<string, string>;
  canWrite: boolean;
  product: CatalogueSearchResult | null;
  quantity: string;
  onProductSelect: (product: CatalogueSearchResult) => void;
  onProductClear: () => void;
  onQuantityChange: (value: string) => void;
  onUpdateLimit: (key: string, value: string) => void;
  onRemoveLimit: (key: string) => void;
  onAdd: () => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <section className="space-y-3">
        <div>
          <p className="text-xs font-medium uppercase text-on-muted tracking-wide ml-1">
            {t("putaway.locations.panel.limits")}
          </p>
          <p className="mt-1 text-sm text-on-secondary">
            {t("putaway.locations.panel.limitsHint")}
          </p>
        </div>

        {limits.length > 0 && (
          <ul className="divide-y divide-border rounded-xl border border-border">
            {limits.map((limit) => (
              <li
                key={limit.key}
                className="flex flex-wrap items-end gap-3 px-3 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-on">
                    {limit.productName}
                  </p>
                </div>
                <Input
                  type="number"
                  min="0"
                  step="any"
                  aria-label={t("putaway.locations.panel.limitFor", {
                    product: limit.productName,
                  })}
                  value={limit.maxQuantity}
                  onChange={(e) => onUpdateLimit(limit.key, e.target.value)}
                  suffix={limit.unitSymbol ?? undefined}
                  error={errors[`quantity-${limit.key}`]}
                  disabled={!canWrite}
                  wrapperClassName="w-36"
                />
                {canWrite && (
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t("putaway.locations.panel.removeAria", {
                      product: limit.productName,
                    })}
                    onClick={() => onRemoveLimit(limit.key)}
                  >
                    <Trash2 size={16} className="text-red-600" />
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {canWrite && (
          <div className="space-y-3 rounded-xl border border-dashed border-border p-3">
            <div>
              <ProductCombobox
                value={product}
                onSelect={onProductSelect}
                onClear={onProductClear}
                search={(q) => documentsProductsApi.productSearch(q)}
                placeholder={t("putaway.locations.panel.productPlaceholder")}
                label={t("putaway.locations.panel.product")}
              />
              {errors.product && (
                <p role="alert" className="mt-1 text-xs text-on-danger">
                  {errors.product}
                </p>
              )}
            </div>
            <Input
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(e) => onQuantityChange(e.target.value)}
              label={t("putaway.locations.panel.quantity")}
              placeholder={t("putaway.locations.panel.quantityPlaceholder")}
              suffix={
                product
                  ? unitLabel(t, product.uom_symbol) || undefined
                  : undefined
              }
              error={errors.quantity}
            />
            <Button variant="outline" onClick={onAdd}>
              {t("putaway.locations.panel.add")}
            </Button>
          </div>
        )}
      </section>
    </>
  );
}
