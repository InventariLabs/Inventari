import type { components } from "@/types/api-generated";
import type { WithServerDefaults } from "@/types/request";
import type { ProductOption } from "@/modules/maker/api/products";

export type BomLine = components["schemas"]["BoMLineRead"];

export type BomMoveRequest = components["schemas"]["BomMoveRequest"];

export type BomTreeNode = components["schemas"]["BomTreeNode"];

export type BomTreeResponse = components["schemas"]["BomTreeResponse"];

export type ProductionStatus = "DRAFT" | "COMPLETED" | "CANCELLED" | "REVERSED";

export type ProductionOrderLine =
  components["schemas"]["ProductionOrderLineRead"];

/**
 * A stock move of a production run, as the maker module serves it: the core
 * StockMove identifiers plus the names needed to render them.
 */
export type StockMove = components["schemas"]["ProductionStockMoveRead"];

export type ProductionOrder = components["schemas"]["ProductionOrderRead"];

export type ProductionOrderCreate =
  components["schemas"]["ProductionOrderCreate"];

export type ProductionOrderUpdate =
  components["schemas"]["ProductionOrderUpdate"];

export type ProductionOrderCancel =
  components["schemas"]["ProductionOrderCancel"];

export type ProductionOrderComplete =
  components["schemas"]["ProductionOrderComplete"];

export type ProductionOrderListResponse =
  components["schemas"]["ProductionOrderListResponse"];

/** One month of the aggregated financial result (dashboard widget). */
export type MonthlyResultItem = components["schemas"]["MonthlyResultItem"];

/** One shelf a planned draw would take from, and how much of it — the
 * same plan completion draws by, read before anything leaves stock. */
export type PlannedDraw = components["schemas"]["CostBreakdownPlannedDraw"];

export type CostBreakdownEntry = components["schemas"]["CostBreakdownEntry"];

export type CostBreakdownResponse =
  components["schemas"]["CostBreakdownResponse"];
/** What the production sheet records: a run already made, or one planned. */
export type ProductionMode = "made" | "planned";

/** The preview plus need / have / short per ingredient and the cost per unit. */
export type ProductionPreviewResponse =
  components["schemas"]["ProductionPreviewResponse"];
export type ShortageShoppingListResponse =
  components["schemas"]["ShortageShoppingListResponse"];

// ---------------------------------------------------------------------------
// Recipes
// ---------------------------------------------------------------------------

export type MakerRecipe = components["schemas"]["RecipeRead"];

export type RecipeCostLine = components["schemas"]["RecipeCostLineRead"];

export type RecipeCostLineKind = "LABOR" | "PACKAGING" | "OVERHEAD" | "OTHER";

export type RecipeCostLineCreate =
  components["schemas"]["RecipeCostLineCreate"];

export type RecipeCostLineUpdate =
  components["schemas"]["RecipeCostLineUpdate"];

export type RecipeCreate =
  components["schemas"]["app__modules__maker___schemas_recipes__RecipeCreate"];

export type RecipeUpdate =
  components["schemas"]["app__modules__maker___schemas_recipes__RecipeUpdate"];

export type RecipeCatalogItem = components["schemas"]["RecipeCatalogItem"];

export type RecipeCatalogResponse =
  components["schemas"]["RecipeCatalogResponse"];

export type MakerSettings = components["schemas"]["MakerSettingsRead"];
export type ReferenceDirection = MakerSettings["reference_direction"];
export type AvailabilityCheckScope = MakerSettings["availability_check_scope"];
export type CreateOnShortageStrategy =
  MakerSettings["create_on_shortage_strategy"];

export type MakerSettingsUpdate = components["schemas"]["MakerSettingsUpdate"];

// ---------------------------------------------------------------------------
// Availability
// ---------------------------------------------------------------------------

export type AvailabilityResponse =
  components["schemas"]["AvailabilityResponse"];

/** One shortage entry in a 422 shortage_blocked / shortage_warning payload. */
export type ShortageEntry = components["schemas"]["ShortageItemRead"];

/**
 * Router state the recipe catalog accepts: an entry point elsewhere in the
 * app (item edit modal) sends a product that has no formula yet, and the
 * catalog opens the create sheet already pointed at it.
 */
export interface RecipeCatalogLocationState {
  createRecipeFor?: ProductOption;
}

/**
 * What a caller sends for the three bodies whose server defaults the contract
 * marks as required: a field it leaves out is the server's default.
 */
export type RecipeCostLineCreateInput = WithServerDefaults<
  RecipeCostLineCreate,
  "sort_order"
>;
export type RecipeCreateInput = WithServerDefaults<
  RecipeCreate,
  "batch_yield_qty" | "is_default"
>;
export type ProductionOrderCreateInput = WithServerDefaults<
  ProductionOrderCreate,
  "confirm_shortage"
>;
