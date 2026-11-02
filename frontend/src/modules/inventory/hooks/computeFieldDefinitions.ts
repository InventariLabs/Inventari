import { SYSTEM_FIELDS } from "@/config/systemFields";
import type {
  CategoryDTO,
  FieldDefinition,
  StorageLocationSummary,
} from "@/types";

interface ComputeContext {
  // The categories endpoints answer CategoryDTO; its field_definitions are
  // typed as open dicts on the wire, so the renderer narrows them once,
  // inside computeFieldDefinitions.
  selectedCategory: CategoryDTO | undefined;
  selectedStorage: StorageLocationSummary | undefined;
  /** Name of the selected UoM's category ("Weight", "Volume", "Count", …),
   * resolved from `uom_id`. `null` when no unit is picked yet. */
  uomCategoryName: string | null;
  /** The stats module's "Show inventory value" switch
   * (`useShowInventoryValue`). Off, the form drops the purchase price — see
   * the rule below. Left out, the field is offered. */
  showInventoryValue?: boolean;
  /** The food database recognised the barcode (`metadata.off_enriched`).
   * Stands in for the category's context while none is chosen, so a scanned
   * jar is treated as food before anybody picks a category. */
  scannedAsFood?: boolean;
}

// A chosen category speaks for itself, even when it carries no context; only
// with none chosen does a food scan stand in for the context.
function contextOf(
  category: CategoryDTO | undefined,
  scannedAsFood: boolean,
): string | null | undefined {
  if (category) return category.context_tag;
  return scannedAsFood ? "food" : undefined;
}

/**
 * What a tracked field names on the product, where the two vocabularies do
 * not say a field in the same words.
 *
 * A location's tracked-field toggles call the product's description "Notes"
 * and its purchase price "Price" (the keys `neutralBaseFields.ts` stores in
 * the location's `context_schema`), while the product form and the item know
 * those fields as `description` and `purchase_price` (`systemFields.ts`).
 * Product code and Shelf / position already carry the product's own key.
 *
 * Both spellings are taken for the same field, so a schema that stores the
 * product's key keeps working — matching the tracked keys straight against
 * the system keys hid the description and the price of every location that
 * turned those toggles on.
 */
const TRACKED_FIELD_ALIASES: Record<string, string> = {
  notes: "description",
  price: "purchase_price",
};

export function computeFieldDefinitions({
  selectedCategory,
  selectedStorage,
  uomCategoryName,
  showInventoryValue = true,
  scannedAsFood = false,
}: ComputeContext): FieldDefinition[] {
  const definedFields: FieldDefinition[] = [];
  const processedKeys = new Set<string>();
  // The category's field definitions cross the wire as open dicts (the DTO
  // types the list loosely); the entries are the shared FieldDefinition
  // shape, so they are narrowed here — the one place that reads them.
  const categoryFields = (selectedCategory?.field_definitions ??
    []) as FieldDefinition[];

  const categoryContext = contextOf(selectedCategory, scannedAsFood);

  // A field set on a level above — a rack, a warehouse — applies here as if
  // the location set it itself: the tracked keys join its own, and the
  // custom fields follow its own, which win a clash with an inherited one.
  // The tracked keys arrive in the storage screens' words ("Notes", "Price")
  // and are translated to the product's field keys where the schema is read
  // as the list of visible fields.
  const storageSchema = [
    ...(selectedStorage?.context_schema ?? []),
    ...(selectedStorage?.inherited_context_schema ?? []).map((f) => f.key),
  ].map((key) => TRACKED_FIELD_ALIASES[key] ?? key);
  const storageFields: FieldDefinition[] = [
    ...(selectedStorage?.field_definitions ?? []),
    ...(selectedStorage?.inherited_field_definitions ?? []).map(
      ({ from_id: _fromId, from_name: _fromName, ...f }) => f,
    ),
  ];

  Object.entries(SYSTEM_FIELDS).forEach(([key, sysConfig]) => {
    let fieldDef: FieldDefinition = { ...sysConfig } as FieldDefinition;

    const categoryOverride = categoryFields.find((f) => f.key === key);

    if (categoryOverride) {
      fieldDef = { ...fieldDef, ...categoryOverride };
    }

    if (categoryContext && sysConfig.contexts) {
      if (!sysConfig.contexts.includes(categoryContext)) {
        fieldDef.visible = false;
      }
    }

    if (storageSchema.length > 0) {
      const alwaysVisible = ["name", "location_id", "quantity"];

      if (alwaysVisible.includes(key)) {
        fieldDef.visible = true;
      } else {
        if (categoryOverride && categoryOverride.visible !== undefined) {
          fieldDef.visible = categoryOverride.visible;
        } else {
          fieldDef.visible = storageSchema.includes(key);
        }
      }
    }

    // The purchase price feeds the stock value, and where the organization
    // does not show that value (the home profile presets it off) the record
    // overview hides the price as well: the field would collect a figure
    // nothing on screen reads back, and on an edit it would show the stored
    // price the overview has just hidden. The switch decides, not the
    // profile, so a pantry whose admin turned the value on gets the field.
    // After the storage context_schema block so no storage can re-show it.
    if (!showInventoryValue && key === "purchase_price") {
      fieldDef.visible = false;
    }

    // A continuous unit means the quantity already carries the weight or
    // volume, so there is nothing left for a separate weight field to hold.
    if (uomCategoryName === "Weight" || uomCategoryName === "Volume") {
      if (key === "weight") {
        fieldDef.visible = false;
      }
      if (key === "quantity") {
        fieldDef.label =
          uomCategoryName === "Weight"
            ? "items:itemWeight"
            : "items:itemVolume";
      }
    } else if (key === "weight") {
      fieldDef.label = "items:itemWeightPerUnit";
    }

    definedFields.push(fieldDef);
    processedKeys.add(key);
  });

  // The category's list crosses the wire as open dicts and was narrowed
  // above, where it is read.
  [...categoryFields, ...storageFields].forEach((f) => {
    if (!processedKeys.has(f.key)) {
      const isSystem = Object.keys(SYSTEM_FIELDS).includes(f.key);
      definedFields.push({
        ...f,
        is_custom: !isSystem,
      });
      processedKeys.add(f.key);
    }
  });

  return definedFields;
}
