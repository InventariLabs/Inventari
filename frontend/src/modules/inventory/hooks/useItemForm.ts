import {
  useState,
  useCallback,
  useMemo,
  useEffect,
  useRef,
  type Dispatch,
  type MutableRefObject,
  type SetStateAction,
} from "react";
import { CategoryDTO, FieldDefinition, ItemCreate, productCode } from "@/types";
import { useTranslation } from "react-i18next";
import { formatDecimalQty } from "@/utils/formatters";
import { toast } from "sonner";
import { useFormMemoryStore } from "@/store/formMemoryStore";
import { computeFieldDefinitions } from "./computeFieldDefinitions";
import { buildSubmissionPayload } from "./buildSubmissionPayload";
import { requiredFieldErrors, settleUnitOnPayload } from "./submitUnit";
import { focusFirstInvalidField } from "../utils/focusFirstInvalidField";
import {
  convertQuantity,
  convertedQuantity,
  templateWeight,
} from "./unitQuantity";
import {
  useUoms,
  findUom,
  getUomCategoryName,
} from "@/modules/shared/hooks/useUoms";
import { useModuleValidation } from "@/hooks/useModuleValidation";
import { useFieldDefinitions } from "./useFieldDefinitions";
import { useUnitChoice } from "./useUnitChoice";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { getLabel } from "@/modules/inventory/components/FieldRenderers/helpers";
import type { CoreFormName } from "@/lib/moduleRegistry/moduleInterfaces";
import type { StorageLocationSummary } from "@/types";
import { useLocationsById } from "@/module-sdk";
import type { LocationScope } from "@/module-sdk";
import { useStorageOffer } from "./useStorageOffer";
export interface ItemFormData {
  // Index signature required because uom field is a nested object
  // and consumers assign ItemFormData to Record<string, unknown>
  [key: string]: unknown;
  name: string;
  location_id: string;
  quantity: string;
  /** The only carrier of the unit. Everything that used to branch on a unit
   * symbol asks the UoM catalogue about this id instead. */
  uom_id?: string;
  /** Weight of a single unit and the unit it is given in. Both belong to the
   * product template, not to this line (ADR-015). */
  weight_uom_id?: string;
  uom?: {
    id: string;
    name: string;
    symbol: string;
    category_name: string;
  } | null;
  metadata: Record<string, unknown>;
  brand: string;
  description: string;
  expiry_date: string;
  freeze_date: string;
  purchase_price: string;
  shelf_location: string;
  category_id: string;
  weight: string;
  barcode: string;
  /** The product's SKU — the template's, like the threshold. */
  sku: string;
  serial_number: string;
  min_quantity: string;
  /** The order the product's stock leaves in — the template's, like the
   * threshold. Empty reads as FIFO. */
  removal_strategy?: string;
  image_url?: string;
}

/** The order the product's stock leaves in, as the form edits it — the
 * template's, or empty (read as FIFO) when it sets none. */
function templateStrategy(data: UseItemFormProps["initialData"]): string {
  return data?.template?.removal_strategy ?? "";
}

/** The product's SKU, as the form edits it — the template's, or empty. */
function templateSku(data: UseItemFormProps["initialData"]): string {
  return data?.template?.sku ?? "";
}

/**
 * The unit the matched product template keeps, as the form shows it.
 *
 * It travels with the form so the hint can sit beside the picker — "this
 * product is kept in kg" before anything is saved — and so a save can tell a
 * deliberate choice from the template's own unit.
 */
export type { PendingUnitChoice, TemplateUnitPrompt } from "./useUnitChoice";

interface UseItemFormProps {
  initialData?: Partial<ItemFormData> & {
    template?: {
      barcode?: string | null;
      sku?: string | null;
      min_quantity?: string;
      weight_value?: number | null;
      weight_uom_id?: string | null;
      removal_strategy?: string | null;
    };
  };
  // The categories endpoints answer CategoryDTO; the form narrows its
  // field definitions inside computeFieldDefinitions.
  categories?: CategoryDTO[];
  /**
   * The scope the location field offers. Given it, the form refuses to save
   * into a place the reader cannot see in the field — a remembered id that
   * has since been deleted or filtered out leaves the picker showing its
   * placeholder, and the product would go somewhere the form cannot even
   * name — and puts the one place there is in the field. Left out on the
   * edit form on purpose: an existing product's own location has to stay
   * saveable whether or not it would be offered today.
   */
  storageScope?: LocationScope;
  /** A place the form arrived holding; offered whatever the scope says. */
  keepStorageId?: string | null;
  onSubmit: (data: Partial<ItemCreate>) => void;
  /**
   * Which core form this is, so enabled modules can contribute validation
   * rules to it (see `useModuleValidation`). Defaults to creation.
   */
  form?: CoreFormName;
}

/**
 * Names the system fields the picked category hides while they carry a value,
 * when there are any. computeFieldDefinitions answers what the
 * form will show, and the payload builder honours the same definitions —
 * whatever it hides leaves the submission together with the value the reader
 * typed into it, so the change has to say so while it happens, before any
 * save.
 */
function warnIfCategoryHidesFilledFields(
  currentDefinitions: FieldDefinition[],
  nextCategory: CategoryDTO | undefined,
  selectedStorage: StorageLocationSummary | undefined,
  uomCategoryName: string | null,
  formData: Record<string, unknown>,
  t: (key: string, opts?: Record<string, unknown>) => string,
  resolveLabel: (field: FieldDefinition) => string,
): void {
  if (!nextCategory) return;
  const nextVisible = new Set(
    computeFieldDefinitions({
      selectedCategory: nextCategory,
      selectedStorage,
      uomCategoryName,
    })
      .filter((f) => f.visible)
      .map((f) => f.key),
  );
  const labels = currentDefinitions
    .filter(
      (f) =>
        f.visible &&
        f.is_custom === false &&
        !nextVisible.has(f.key) &&
        formData[f.key] !== undefined &&
        formData[f.key] !== null &&
        formData[f.key] !== "",
    )
    .map(resolveLabel);
  if (labels.length > 0) {
    toast.warning(
      t("items:messages.fieldsHiddenByCategory", { fields: labels.join(", ") }),
    );
  }
}

/**
 * A stored quantity as the form's input should hold it. The API sends the
 * column's full scale ("20.000"), and the Edit sheet printed it verbatim for
 * a product counted in pieces, where the add form, the list and the page say
 * 20. The padding goes; the value does not change.
 */
function editableQuantity(quantity: unknown, whenMissing = ""): string {
  return quantity == null
    ? whenMissing
    : formatDecimalQty(quantity as string | number);
}

/** The fields of `current` that differ from `base` — an edit in progress. */
function changedSince(
  base: ItemFormData,
  current: ItemFormData,
): Partial<ItemFormData> {
  const baseFields = base as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(current).filter(
      ([key, value]) =>
        JSON.stringify(value) !== JSON.stringify(baseFields[key]),
    ),
  );
}

/** What the form holds before anybody touches it.
 *
 * Three answers in order: the record the form was opened on, the two fields
 * batch mode remembers (where the goods go and what they are — see
 * `formMemoryStore`), or nothing at all. Written out here so the hook reads
 * as what it does with the state rather than as how the state is spelled.
 */
function initialFormState(
  initialData: UseItemFormProps["initialData"],
  lastItem: Partial<ItemCreate> | null,
): ItemFormData {
  // If we have explicit initialData, use it
  if (
    initialData &&
    Object.keys(initialData).length > 0 &&
    (initialData.name || initialData.barcode)
  ) {
    return {
      name: "",
      location_id: "",
      ...initialData,
      quantity: editableQuantity(initialData.quantity, "1"),
      metadata: initialData?.metadata || {},
      brand: initialData?.brand || "",
      description: initialData?.description || "",
      expiry_date: initialData?.expiry_date || "",
      freeze_date: initialData?.freeze_date || "",
      // `??`, not `||`: a price of 0 is a price, and blanking it here is how
      // a free item came back from the form with no price at all.
      purchase_price: initialData?.purchase_price ?? "",
      shelf_location: initialData?.shelf_location || "",
      category_id: initialData?.category_id || "",
      weight: templateWeight(initialData).weight ?? "",
      weight_uom_id: templateWeight(initialData).weight_uom_id,
      barcode: productCode(initialData) ?? "",
      sku: templateSku(initialData),
      serial_number: initialData?.serial_number || "",
      min_quantity:
        initialData?.min_quantity ?? initialData?.template?.min_quantity ?? "",
      removal_strategy: templateStrategy(initialData),
    };
  }

  // Otherwise, check if we have "memory" from previous item (Batch mode).
  // Two fields describe the batch — where it is going and what it is — and
  // they are the only two that carry over; see `formMemoryStore`.
  if (lastItem) {
    return {
      name: "",
      location_id: lastItem.location_id || "",
      category_id: lastItem.category_id || "",
      quantity: "1",
      metadata: {},
      brand: "",
      description: "",
      expiry_date: "",
      freeze_date: "",
      purchase_price: "",
      shelf_location: "",
      weight: "",
      barcode: "",
      sku: "",
      serial_number: "",
      min_quantity: "",
    };
  }

  // Default empty state
  return {
    name: "",
    location_id: "",
    quantity: "1",
    metadata: {},
    brand: "",
    description: "",
    expiry_date: "",
    freeze_date: "",
    purchase_price: "",
    shelf_location: "",
    category_id: "",
    weight: "",
    barcode: "",
    sku: "",
    serial_number: "",
    min_quantity: "",
  };
}

/**
 * The single location the picker offers, put in the field rather than
 * asked for: one place to put a product is no decision, and the reader's
 * click is worth more than confirming it.
 *
 * One chance only — the first answer the endpoint gives decides. Seeding
 * again afterwards would fill a field the reader deliberately cleared.
 * The exception is a value the picker never offered: that is not the
 * reader's choice but a remembered pick on its way out (`useMissingPicks`
 * clears it), so the chance stays unspent until the field is genuinely empty
 * or holds what it is offered. The default goes into
 * `pristineRef` as well as into the form: a choice nobody made is not an
 * unsaved change, and the leave guard must not ask about a form the
 * reader never touched.
 */
function useSoleStorageSeed({
  soleId,
  chosenOffered,
  storageLocationId,
  setFormData,
  pristineRef,
}: {
  soleId: string | null | undefined;
  chosenOffered: boolean | undefined;
  storageLocationId: string;
  setFormData: Dispatch<SetStateAction<ItemFormData>>;
  pristineRef: MutableRefObject<ItemFormData>;
}): void {
  const decided = useRef(false);
  useEffect(() => {
    if (soleId === undefined || decided.current) return;
    // A value is being checked: wait for the answer.
    if (storageLocationId !== "" && chosenOffered === undefined) return;
    if (soleId === null || chosenOffered === true) {
      decided.current = true;
      return;
    }
    // A remembered id the picker cannot offer is being cleared rather than
    // kept; wait for the field to be empty, then give it the one place.
    if (storageLocationId) return;
    decided.current = true;
    const seeded = { ...pristineRef.current, location_id: soleId };
    pristineRef.current = seeded;
    setFormData((prev) => ({ ...prev, location_id: soleId }));
  }, [soleId, chosenOffered, storageLocationId, setFormData, pristineRef]);
}

export function useItemForm({
  initialData,
  categories,
  storageScope,
  keepStorageId,
  onSubmit,
  form = "item_create",
}: UseItemFormProps) {
  const { t } = useTranslation(["items", "common"]);
  const tDyn = makeTDynamic(t);
  const { lastItem, setLastItem } = useFormMemoryStore();

  const [formData, setFormData] = useState<ItemFormData>(() =>
    initialFormState(initialData, lastItem),
  );

  const lastAppliedInitialDataRef = useRef<string>("");
  /**
   * The form as it stood when it was last filled from the record — the
   * yardstick for "are there unsaved changes". Seeded from the initial state
   * so a form that was never re-filled still has one.
   */
  const pristineRef = useRef<ItemFormData>(formData);

  useEffect(() => {
    if (!initialData) return;

    // Guard against infinite re-renders caused by unstable object references.
    // React compares deps by reference, so a new object literal on every render
    // would cause this effect to fire on every render → infinite loop.
    const serialized = JSON.stringify(initialData);
    if (serialized === lastAppliedInitialDataRef.current) return;
    lastAppliedInitialDataRef.current = serialized;

    // The item's own `weight` is a computed total; what the form edits is the
    // product's unit weight, which comes off the template.
    const displayData = { ...initialData, ...templateWeight(initialData) };
    delete displayData.template;
    if (initialData.quantity != null) {
      displayData.quantity = editableQuantity(initialData.quantity);
    }

    // What the record says now, laid over the form as it was last filled.
    const before = pristineRef.current;
    const filled: ItemFormData = {
      ...before,
      ...displayData,
      metadata: initialData.metadata || before.metadata || {},
      // A product's code lives on the product, where a scan reads it and
      // where the record's own save puts it, so the record's column is
      // empty for nearly every product that has one.
      barcode: productCode(initialData) ?? before.barcode,
      sku: initialData.template?.sku ?? before.sku ?? "",
      min_quantity:
        initialData.min_quantity ??
        initialData.template?.min_quantity ??
        before.min_quantity ??
        "",
      removal_strategy: templateStrategy(initialData),
    };
    pristineRef.current = filled;
    // The record is refetched under an open form whenever something else
    // changes it (freeing its label from the same sheet, say). What the
    // reader has already changed stays as typed; every other field takes the
    // record's answer, so a form nobody touched still follows the record.
    setFormData((prev) => ({ ...filled, ...changedSince(before, prev) }));
  }, [initialData]);

  /**
   * The single location the picker offers, put in the field rather than
   * asked for — see `useSoleStorageSeed`.
   */
  const { soleId, chosenOffered } = useStorageOffer(
    storageScope,
    formData.location_id as string,
    keepStorageId,
  );
  useSoleStorageSeed({
    soleId,
    chosenOffered,
    storageLocationId: formData.location_id,
    setFormData,
    pristineRef,
  });

  const [errors, setErrors] = useState<Record<string, string>>({});
  const runModuleRules = useModuleValidation(form);
  /** The unit the record already carries — what "changed the unit" is read
   * against on the edit form. */
  const initialUomId =
    typeof initialData?.uom_id === "string" ? initialData.uom_id : undefined;

  const { data: uomCategories } = useUoms();

  /**
   * Which unit the catalogue will count this product in, and the confirmation
   * a different choice owes the server. See `useUnitChoice`.
   */
  const adoptTemplateUnit = useCallback(
    (uomId: string) => {
      setFormData((prev) =>
        prev.uom_id === uomId ? prev : { ...prev, uom_id: uomId },
      );
    },
    [setFormData],
  );

  const revertToTemplateUnit = useCallback(
    (chosenUomId: string, templateUomId: string) => {
      setFormData((prev) => ({
        ...prev,
        uom_id: templateUomId,
        quantity: convertQuantity(
          prev.quantity,
          findUom(uomCategories, chosenUomId),
          findUom(uomCategories, templateUomId),
        ),
      }));
    },
    [uomCategories],
  );

  const {
    templateUnit,
    templateUomId,
    pendingUnitChoice,
    resolveUnitChoice,
    askIfDifferent,
    isConfirmedChoice,
    isDifferentFromTemplate,
    unitLookupFailed,
    retryUnitLookup,
  } = useUnitChoice({
    active: form === "item_create",
    name: formData.name as string | undefined,
    barcode: formData.barcode as string | undefined,
    onAdoptTemplateUnit: adoptTemplateUnit,
    onRevertToTemplateUnit: revertToTemplateUnit,
  });

  // The chosen place is read by id: the form needs its type and fields, not
  // the organization's catalogue.
  const { byId: chosenPlace } = useLocationsById([
    formData.location_id as string,
  ]);
  const selectedStorage = chosenPlace.get(formData.location_id as string);

  const selectedStorageType = useMemo(
    () => selectedStorage?.location_type ?? undefined,
    [selectedStorage],
  );

  const selectedCategory = useMemo(
    () => categories?.find((c) => c.id === formData.category_id),
    [categories, formData.category_id],
  );

  // The form no longer pre-fills pieces on a new item. Which unit a record
  // carries is decided once, by the backend: a matched template is
  // knowledge and its unit wins, pieces are the answer for a product the
  // catalogue says nothing about. A form that shipped pcs itself was
  // overruling the template before the backend ever saw the request — a
  // record contradicting its own catalogue row, pieces counted as
  // kilograms on the stock screen. Leaving the unit unset here lets the
  // one rule own the answer; the selector starts empty and the saved
  // record shows the unit that was actually applied.

  const uomCategoryName = useMemo(
    () => getUomCategoryName(uomCategories, formData.uom_id),
    [uomCategories, formData.uom_id],
  );

  // The per-profile rules (the home profile drops the purchase-price field)
  // live in the sibling hook; the form just consumes the list.
  const fieldDefinitions = useFieldDefinitions({
    selectedCategory,
    selectedStorage,
    uomCategoryName,
    scannedAsFood: Boolean(formData.metadata?.off_enriched),
  });

  const handleInputChange = useCallback(
    (name: string, value: unknown, isMetadata: boolean = false) => {
      if (isMetadata) {
        setFormData((prev) => ({
          ...prev,
          metadata: {
            ...prev.metadata,
            [name]: value,
          },
        }));
      } else {
        const strValue = value as string;
        if (name === "uom_id") {
          // A unit the matched product is not counted in is a deliberate
          // choice, and the server will not take it unconfirmed (AGENTS.md
          // §4). Asking here keeps the refusal from being the first the
          // reader hears of it. See `useUnitChoice`.
          askIfDifferent(strValue);
          setFormData((prev) => {
            // The quantity converts from the unit the form is holding, read
            // inside the update rather than off the render that started the
            // change: a prefill landing in between would otherwise restate
            // "500 g" from the unit the reader had replaced a moment ago.
            const nextQuantity = convertedQuantity(
              prev,
              strValue,
              uomCategories,
            );
            // Losing the quantity is not something to discover by looking.
            if (prev.quantity && !nextQuantity) {
              toast.info(t("items:messages.quantityClearedOnUnitChange"));
            }
            return {
              ...prev,
              uom_id: strValue,
              quantity: nextQuantity,
            };
          });
        } else {
          // See warnIfCategoryHidesFilledFields — a category change that
          // drops a filled value from the submission must say so while it
          // happens.
          if (name === "category_id" && strValue !== formData.category_id) {
            warnIfCategoryHidesFilledFields(
              fieldDefinitions,
              categories?.find((c) => c.id === strValue),
              selectedStorage,
              uomCategoryName,
              formData,
              t,
              (f) => getLabel(f, tDyn),
            );
          }
          setFormData(
            (prev) => ({ ...prev, [name]: strValue }) as ItemFormData,
          );
        }
      }

      if (errors[name]) {
        setErrors((prev) => {
          const { [name]: _, ...rest } = prev;
          return rest;
        });
      }
    },
    [
      errors,
      uomCategories,
      formData,
      t,
      tDyn,
      categories,
      selectedStorage,
      uomCategoryName,
      fieldDefinitions,
      askIfDifferent,
    ],
  );

  // Backward compatibility alias
  const handleMetadataChange = useCallback(
    (key: string, value: unknown) => {
      handleInputChange(key, value, true);
    },
    [handleInputChange],
  );

  const submit = useCallback(
    (e?: React.FormEvent) => {
      if (e) e.preventDefault();

      const newErrors: Record<string, string> = requiredFieldErrors(
        fieldDefinitions,
        formData,
        t("common:labels.required"),
      );

      if (!formData.name?.trim())
        newErrors.name = t("items:validation.nameRequired");
      if (!formData.location_id) {
        newErrors.location_id = t("items:validation.storageRequired");
      } else if (chosenOffered === false) {
        newErrors.location_id = t("items:validation.storageUnavailable");
      }

      // Module rules run last and never overwrite a core message: the core
      // form owns its own fields, modules only add findings of their own.
      for (const [field, message] of Object.entries(
        runModuleRules(formData as Record<string, unknown>),
      )) {
        if (!newErrors[field]) newErrors[field] = message;
      }

      if (Object.keys(newErrors).length > 0) {
        setErrors(newErrors);
        // The first field with a problem may be far below the button that was
        // pressed; without this the press looks dead.
        focusFirstInvalidField(Object.keys(newErrors));
        return;
      }

      // Without the catalogue's answer the unit question is skipped, and the
      // server then refuses the save. Say so now and ask again instead.
      if (unitLookupFailed) {
        toast.error(t("items:messages.unitLookupFailed"));
        retryUnitLookup();
        return;
      }

      const chosenUomId = formData.uom_id;
      // A unit the matched product is not counted in is a choice the server
      // will not take unconfirmed, whatever path set it. The picker asks
      // first, so an unconfirmed one here means the form was handed a unit
      // nobody was asked about yet — ask now, and hold the save until the
      // reader answers.
      if (
        isDifferentFromTemplate(chosenUomId) &&
        !isConfirmedChoice(chosenUomId)
      ) {
        askIfDifferent(chosenUomId);
        return;
      }

      const submission = settleUnitOnPayload(
        buildSubmissionPayload(
          formData as Record<string, unknown>,
          fieldDefinitions,
          form === "item_create" ? "create" : "update",
        ),
        chosenUomId,
        { templateUomId, isConfirmedChoice, initialUomId },
      );

      // Only a new product feeds the batch-mode memory. Fixing a category on
      // an existing record used to set the default for the next new one,
      // which is how a correction on one item became a wrong value on the
      // next.
      if (form === "item_create") setLastItem(submission);
      onSubmit(submission);
    },
    [
      formData,
      onSubmit,
      t,
      fieldDefinitions,
      setLastItem,
      runModuleRules,
      form,
      chosenOffered,
      askIfDifferent,
      isConfirmedChoice,
      isDifferentFromTemplate,
      unitLookupFailed,
      retryUnitLookup,
      templateUomId,
      initialUomId,
    ],
  );

  /**
   * Whether anything in the form differs from the record behind it.
   *
   * Compared key by key rather than by serialising the whole object: a new
   * field added to the form would change the serialised order and report
   * every untouched form as edited.
   */
  const isDirty = useMemo(() => {
    const pristine = pristineRef.current as Record<string, unknown>;
    const current = formData as Record<string, unknown>;
    const keys = new Set([...Object.keys(pristine), ...Object.keys(current)]);
    for (const key of keys) {
      // The template's own unit is not a change the reader made: it is the
      // answer the save would get anyway, and the payload leaves it out (see
      // `submit`). Counting it here reported every brand-new product the
      // catalogue knows as edited the moment its form opened.
      if (key === "uom_id" && templateUomId === current.uom_id) {
        continue;
      }
      if (JSON.stringify(pristine[key]) !== JSON.stringify(current[key])) {
        return true;
      }
    }
    return false;
  }, [formData, templateUomId]);

  return {
    formData,
    setFormData,
    isDirty,
    errors,
    setErrors,
    fieldDefinitions,
    handleInputChange,
    handleMetadataChange,
    submit,
    selectedStorageType,
    /** Whether the place the field holds is one the picker offers;
     * `undefined` while that is not known (or the form checks nothing). */
    storageOffered: chosenOffered,
    /** Category of the selected unit ("Weight", "Volume", "Count", …) —
     * the single answer to "is this item counted or weighed". */
    uomCategoryName,
    /** The unit the matched product template keeps, when the catalogue knows
     * the product being typed — the hint beside the picker. */
    templateUnit,
    /** A chosen unit the template does not keep, waiting on the reader. */
    pendingUnitChoice,
    resolveUnitChoice,
  };
}
