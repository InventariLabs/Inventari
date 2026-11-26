import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FileSource } from "@/components/import/ImportWizardSheet";
import type { ItemImportOutcome } from "@/components/import/types";
import { itemsApi, type GrocyFileAnalysis } from "@/lib/api/items";
import { useImportGrocy } from "@/modules/inventory/hooks/useItemMutations";
import type { CategoryDTO } from "@/types";
import { GrocyFileReview } from "./GrocyFileReview";
import { grocyCategoryMatches } from "./grocyCategoryMatches";

/**
 * The products import's second source: a move from Grocy's database file.
 *
 * Grocy writes no export, so its tile takes `grocy.db` itself. The file is
 * read first and reviewed in place of a sheet's column mapping — what it
 * holds, what the move would create, what stays in Grocy — and the move then
 * sends the Grocy groups this screen recognised as categories already here,
 * by the names it shows them under. `active` says the last file read was
 * Grocy's, so the summary words what it skipped as an earlier move's;
 * `forget` is called when a sheet is read instead.
 */
export function useGrocySource(categories: CategoryDTO[] | undefined): {
  source: FileSource<ItemImportOutcome>;
  active: boolean;
  forget: () => void;
} {
  const { t } = useTranslation(["items"]);
  const importGrocy = useImportGrocy();
  const [analysis, setAnalysis] = useState<GrocyFileAnalysis | null>(null);
  const categoryMatches = useMemo(
    () => grocyCategoryMatches(analysis?.new_categories ?? [], categories, t),
    [analysis, categories, t],
  );
  return {
    active: analysis !== null,
    forget: () => setAnalysis(null),
    source: {
      label: t("items:import.grocy"),
      hint: t("items:import.grocyHint"),
      note: t("items:import.grocyMove.pickBody"),
      accept: ".db,.sqlite,.sqlite3",
      read: async (file) => setAnalysis(await itemsApi.analyzeGrocy(file)),
      review: (file) =>
        analysis && (
          <GrocyFileReview
            fileName={file.name}
            analysis={analysis}
            categoryMatches={categoryMatches}
          />
        ),
      runLabel: t("items:import.grocyMove.move"),
      run: (file, onProgress) =>
        importGrocy.mutateAsync({ file, categoryMatches, onProgress }),
    },
  };
}
