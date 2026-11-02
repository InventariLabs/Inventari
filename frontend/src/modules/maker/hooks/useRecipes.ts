import { keepPreviousData } from "@tanstack/react-query";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import { useAppMutation } from "@/lib/api/mutationFactory";
import {
  recipeApi,
  type BomLineCreate,
  type BomLineUpdate,
} from "@/modules/maker/api/recipes";
import type {
  MakerSettings,
  MakerSettingsUpdate,
  RecipeCostLineCreateInput,
  RecipeCostLineUpdate,
  RecipeCreateInput,
  RecipeUpdate,
} from "@/modules/maker/types/maker";

export function useMakerRecipeCatalog(
  search?: string,
  sort: string = "newest",
  skip: number = 0,
  limit: number = 50,
) {
  return useModuleQuery("maker", {
    queryKey: queryKeys.maker.recipeCatalog(search, sort, skip, limit),
    queryFn: () => recipeApi.catalog(search, sort, skip, limit),
    placeholderData: keepPreviousData,
  });
}

export function useMakerRecipe(recipeId: string | undefined) {
  return useModuleQuery("maker", {
    queryKey: queryKeys.maker.recipeDetail(recipeId),
    queryFn: () => recipeApi.get(recipeId as string),
    extraEnabled: !!recipeId,
  });
}

export function useCreateMakerRecipe() {
  return useAppMutation(
    (data: RecipeCreateInput) => recipeApi.create(data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useUpdateMakerRecipe() {
  return useAppMutation(
    ({ recipeId, data }: { recipeId: string; data: RecipeUpdate }) =>
      recipeApi.update(recipeId, data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

/** Delete one formula. Production history that referenced it is kept. */
export function useDeleteMakerRecipe() {
  return useAppMutation(
    (recipeId: string) => recipeApi.delete(recipeId),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useAddCostLine() {
  return useAppMutation(
    ({
      recipeId,
      data,
    }: {
      recipeId: string;
      data: RecipeCostLineCreateInput;
    }) => recipeApi.createCostLine(recipeId, data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useUpdateCostLine() {
  return useAppMutation(
    ({
      recipeId,
      lineId,
      data,
    }: {
      recipeId: string;
      lineId: string;
      data: RecipeCostLineUpdate;
    }) => recipeApi.updateCostLine(recipeId, lineId, data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useDeleteCostLine() {
  return useAppMutation(
    ({ recipeId, lineId }: { recipeId: string; lineId: string }) =>
      recipeApi.deleteCostLine(recipeId, lineId),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useAddBomLineToRecipe() {
  return useAppMutation(
    ({ recipeId, data }: { recipeId: string; data: BomLineCreate }) =>
      recipeApi.addBomLine(recipeId, data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useDeleteBomLine() {
  return useAppMutation(
    ({ recipeId, lineId }: { recipeId: string; lineId: string }) =>
      recipeApi.deleteBomLine(recipeId, lineId),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useUpdateBomLine() {
  return useAppMutation(
    ({
      recipeId,
      lineId,
      data,
    }: {
      recipeId: string;
      lineId: string;
      data: BomLineUpdate;
    }) => recipeApi.updateBomLine(recipeId, lineId, data),
    (queryClient) => invalidation.maker(queryClient),
  );
}

export function useMakerSettings() {
  return useModuleQuery("maker", {
    queryKey: queryKeys.maker.recipeSettings,
    queryFn: () => recipeApi.getSettings(),
  });
}

export function useUpdateMakerSettings() {
  return useAppMutation(
    (data: MakerSettingsUpdate) => recipeApi.updateSettings(data),
    (queryClient, settings: MakerSettings) => {
      // Seed the cache before invalidating so the settings panel renders the
      // saved values immediately instead of flashing the previous ones while
      // the refetch is in flight — behaviour carried over from the hand-rolled
      // mutation this replaced.
      queryClient.setQueryData(queryKeys.maker.recipeSettings, settings);
      invalidation.maker(queryClient);
    },
  );
}

export function useMakerRecipeAvailability(
  recipeId: string | undefined,
  batches?: string,
  locationId?: string,
) {
  return useModuleQuery("maker", {
    queryKey: queryKeys.maker.recipeAvailability(recipeId, batches, locationId),
    queryFn: () =>
      recipeApi.getAvailability(recipeId as string, {
        batches,
        location_id: locationId,
      }),
    extraEnabled: !!recipeId,
  });
}
