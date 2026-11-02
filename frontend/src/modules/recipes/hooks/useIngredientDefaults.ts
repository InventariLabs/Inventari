import { useQueryClient } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { useCallback } from "react";
import { useDebouncedCallback } from "@/module-sdk";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type {
  IngredientDefaultCreate,
  IngredientDefaultListResponse,
  IngredientDefaultLookupResponse,
} from "@/modules/recipes/types/nutrition-defaults";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

const ingredientDefaultsKeys = {
  all: ["ingredientDefaults"] as const,
  list: (params: { lang?: string; q?: string; page?: number }) =>
    [...ingredientDefaultsKeys.all, "list", params] as const,
  lookup: (name: string, lang: string) =>
    [...ingredientDefaultsKeys.all, "lookup", name, lang] as const,
};

// ---------------------------------------------------------------------------
// List hook
// ---------------------------------------------------------------------------

export function useIngredientDefaultsList(params?: {
  lang?: string;
  q?: string;
  limit?: number;
  offset?: number;
}) {
  return useModuleQuery<IngredientDefaultListResponse>("recipes", {
    queryKey: ingredientDefaultsKeys.list(params ?? {}),
    queryFn: () => recipesApi.listIngredientDefaults(params),
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Single lookup hook (used in RecipeForm for auto-fill)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Debounced lookup helper (for use in RecipeForm onBlur)
// ---------------------------------------------------------------------------

export function useDebouncedIngredientLookup(lang = "en") {
  const queryClient = useQueryClient();

  const fetchLookup = useCallback(
    (name: string, onResult: (r: IngredientDefaultLookupResponse) => void) => {
      void (async () => {
        try {
          const result = await queryClient.fetchQuery({
            queryKey: ingredientDefaultsKeys.lookup(name, lang),
            queryFn: () => recipesApi.lookupIngredientDefault(name, lang),
            staleTime: 5 * 60_000,
          });
          onResult(result);
        } catch {
          // silent — lookup is best-effort
        }
      })();
    },
    [queryClient, lang],
  );

  // The shared debounce also cancels on unmount, which the hand-rolled timer
  // here did not: the lookup still landed, in a form that had closed.
  const debounced = useDebouncedCallback(fetchLookup, 400);

  return useCallback(
    (
      name: string,
      onResult: (result: IngredientDefaultLookupResponse) => void,
    ) => {
      const trimmed = name.trim();
      if (trimmed.length < 2) return;
      debounced(trimmed, onResult);
    },
    [debounced],
  );
}

// ---------------------------------------------------------------------------
// Mutation hooks (for IngredientDefaultsPage)
// ---------------------------------------------------------------------------

export function useCreateIngredientDefault() {
  return useAppMutation(
    (data: IngredientDefaultCreate) => recipesApi.createIngredientDefault(data),
    (qc) => {
      qc.invalidateQueries({ queryKey: ingredientDefaultsKeys.all });
    },
  );
}

export function useDeleteIngredientDefault() {
  return useAppMutation(
    (id: string) => recipesApi.deleteIngredientDefault(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: ingredientDefaultsKeys.all });
    },
  );
}

export function useImportIngredientDefaults() {
  return useAppMutation(
    ({ file, lang }: { file: File; lang?: string }) =>
      recipesApi.importIngredientDefaults(file, lang),
    (qc) => {
      qc.invalidateQueries({ queryKey: ingredientDefaultsKeys.all });
    },
  );
}
