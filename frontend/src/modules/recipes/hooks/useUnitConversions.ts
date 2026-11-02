import { useAppMutation } from "@/lib/api/mutationFactory";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type {
  UnitConversionCreate,
  UnitConversionUpdate,
} from "@/modules/recipes/types/nutrition-defaults";
import { useModuleQuery } from "@/hooks/queries/useModuleQuery";

const keys = {
  all: ["unitConversions"] as const,
  list: (lang: string) => [...keys.all, "list", lang] as const,
};

export function useUnitConversions(lang = "en") {
  return useModuleQuery("recipes", {
    queryKey: keys.list(lang),
    queryFn: () => recipesApi.listUnitConversions({ lang }),
    staleTime: 60_000,
  });
}

export function useCreateUnitConversion() {
  return useAppMutation(
    (data: UnitConversionCreate) => recipesApi.createUnitConversion(data),
    (qc) => {
      qc.invalidateQueries({ queryKey: keys.all });
    },
  );
}

export function useUpdateUnitConversion() {
  return useAppMutation(
    ({ id, data }: { id: string; data: UnitConversionUpdate }) =>
      recipesApi.updateUnitConversion(id, data),
    (qc) => {
      qc.invalidateQueries({ queryKey: keys.all });
    },
  );
}

export function useDeleteUnitConversion() {
  return useAppMutation(
    (id: string) => recipesApi.deleteUnitConversion(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: keys.all });
    },
  );
}
