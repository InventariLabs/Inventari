import type { ShortageEntry } from "@/modules/maker/types/maker";

/** Shape of the shortage payload from a maker 422 response. */
interface ShortageErrorInfo {
  error: "shortage_blocked" | "shortage_warning" | "insufficient_stock";
  shortages: ShortageEntry[];
  /**
   * Whether the run was born over stock — the server recorded the fact at
   * creation, so the refusal can say "never enough" instead of inventing
   * history. Undefined when an older backend omits it.
   */
  shortAtCreate?: boolean;
}

/**
 * Extracts the shortage payload from an API error, if present.
 * Maker endpoints return 422 with `detail: {error, shortages}` for
 * shortage_blocked / shortage_warning (create) and insufficient_stock
 * (complete). Returns null for any other error shape.
 */
export function parseShortageError(err: unknown): ShortageErrorInfo | null {
  const axiosErr = err as {
    response?: {
      data?: {
        detail?: {
          error?: string;
          shortages?: unknown;
          short_at_create?: unknown;
        };
      };
    };
  };
  const detail = axiosErr.response?.data?.detail;
  if (
    detail &&
    typeof detail === "object" &&
    Array.isArray(detail.shortages) &&
    (detail.error === "shortage_blocked" ||
      detail.error === "shortage_warning" ||
      detail.error === "insufficient_stock")
  ) {
    return {
      error: detail.error,
      shortages: detail.shortages as ShortageEntry[],
      shortAtCreate:
        typeof detail.short_at_create === "boolean"
          ? detail.short_at_create
          : undefined,
    };
  }
  return null;
}

/** Shape of the `empty_bom` payload a maker 422 carries on complete. */
export interface EmptyBomErrorInfo {
  recipeId: string | null;
  recipeName: string | null;
}

/**
 * Extracts the `empty_bom` payload from an API error, if present.
 * Completing a run whose formula lists no ingredients is refused — the
 * response names the formula so the operator can be sent to compose it.
 */
export function parseEmptyBomError(err: unknown): EmptyBomErrorInfo | null {
  const axiosErr = err as {
    response?: {
      data?: {
        detail?: {
          error?: string;
          recipe_id?: string | null;
          recipe_name?: string | null;
        };
      };
    };
  };
  const detail = axiosErr.response?.data?.detail;
  if (detail && typeof detail === "object" && detail.error === "empty_bom") {
    return {
      recipeId: detail.recipe_id ?? null,
      recipeName: detail.recipe_name ?? null,
    };
  }
  return null;
}
