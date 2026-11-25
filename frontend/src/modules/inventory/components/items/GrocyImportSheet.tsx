import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ArrowRight, Database, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { ImportProgressStep } from "@/module-sdk";
import type {
  ImportProgress,
  ItemImportOutcome,
} from "@/components/import/types";
import { extractApiError } from "@/lib/errors";
import { itemsApi, type GrocyFileAnalysis } from "@/lib/api/items";
import { useImportGrocy } from "@/modules/inventory/hooks/useItemMutations";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { grocyCategoryMatches } from "./grocyCategoryMatches";
import { GrocyFileReview } from "./GrocyFileReview";
import { GrocyLeftBehindList } from "./GrocyLeftBehindList";
import { ImportFoundedList } from "./ImportFoundedList";

interface Props {
  onClose: () => void;
  /** The sentence under the result's title, the product import's own. */
  summary: (result: ItemImportOutcome) => string;
}

type Step = "pick" | "review" | "processing" | "result";

/** A move from Grocy. Grocy writes no export, so the move reads its database
 *  file: pick `grocy.db`, read what it holds and what stays behind, then
 *  move — a long file in the background, like a long sheet. */
export function GrocyImportSheet({ onClose, summary }: Props) {
  const { t } = useTranslation(["common", "items"]);
  const importGrocy = useImportGrocy();
  const picker = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<GrocyFileAnalysis | null>(null);
  const [progress, setProgress] = useState<ImportProgress | null>(null);
  const [result, setResult] = useState<ItemImportOutcome | null>(null);
  const { data: categories } = useAllCategories();
  const categoryMatches = useMemo(
    () => grocyCategoryMatches(analysis?.new_categories ?? [], categories, t),
    [analysis, categories, t],
  );

  const read = async (chosen: File) => {
    setFile(chosen);
    try {
      setAnalysis(await itemsApi.analyzeGrocy(chosen));
      setStep("review");
    } catch (error) {
      toast.error(
        extractApiError(error, t("items:import.grocyMove.analyzeFailed")),
      );
    }
  };

  const move = async () => {
    if (!file) return;
    setProgress(null);
    setStep("processing");
    try {
      setResult(
        await importGrocy.mutateAsync({
          file,
          categoryMatches,
          onProgress: setProgress,
        }),
      );
      setStep("result");
    } catch (error) {
      toast.error(
        extractApiError(error, t("items:import.grocyMove.importFailed")),
      );
      setStep("review");
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="3xl"
      backdropOpacity={60}
      aria-label={t("items:import.grocyMove.title")}
    >
      <div className="p-8 border-b flex items-center justify-between bg-surface/50">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-primary-600 text-white rounded-2xl">
            <Database size={24} />
          </div>
          <div>
            <h2 className="text-xl font-semibold text-on tracking-tight">
              {t("items:import.grocyMove.title")}
            </h2>
            <p className="text-xs text-on-secondary font-medium uppercase tracking-widest mt-0.5">
              {t("items:import.grocyMove.formats")}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:a11y.close")}
        >
          <X size={24} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
        {step === "pick" && (
          <div className="space-y-4 py-6 max-w-xl">
            <h3 className="text-base font-semibold text-on">
              {t("items:import.grocyMove.pickTitle")}
            </h3>
            <p className="text-sm text-on-secondary">
              {t("items:import.grocyMove.pickBody")}
            </p>
            <Button onClick={() => picker.current?.click()}>
              <Database size={16} />
              <span>{t("items:import.grocyMove.pickButton")}</span>
            </Button>
            <input
              ref={picker}
              type="file"
              accept=".db,.sqlite,.sqlite3"
              className="hidden"
              aria-label={t("items:import.grocyMove.pickButton")}
              onChange={(event) => {
                const chosen = event.target.files?.[0];
                // Cleared, so choosing the same file again reads it again.
                event.target.value = "";
                if (chosen) void read(chosen);
              }}
            />
          </div>
        )}

        {step === "review" && analysis && file && (
          <GrocyFileReview
            fileName={file.name}
            analysis={analysis}
            categoryMatches={categoryMatches}
          />
        )}

        {(step === "processing" || step === "result") && (
          <ImportProgressStep
            isProcessing={step === "processing"}
            importResult={result}
            waitText={t("items:import.grocyMove.wait")}
            addedText={(count) => t("items:import.added", { count })}
            summaryText={result ? summary(result) : undefined}
            progress={progress}
          >
            {result && <GrocyMoveDetails result={result} />}
          </ImportProgressStep>
        )}
      </div>

      <SheetFooter>
        <SheetActions>
          {step === "pick" && (
            <Button
              variant="ghost"
              onClick={onClose}
              className="uppercase text-[10px] tracking-[0.2em]"
            >
              {t("common:actions.cancel")}
            </Button>
          )}
          {step === "review" && (
            <>
              <Button
                variant="ghost"
                onClick={() => setStep("pick")}
                className="uppercase text-[10px] tracking-[0.2em]"
              >
                {t("common:actions.back")}
              </Button>
              <Button onClick={() => void move()}>
                <span>{t("items:import.grocyMove.move")}</span>
                <ArrowRight size={20} />
              </Button>
            </>
          )}
          {step === "result" && (
            <Button onClick={onClose}>{t("items:import.closeAndView")}</Button>
          )}
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}

/** What the move created beside the products, what it skipped as already
 *  here, and what stayed in Grocy. */
function GrocyMoveDetails({ result }: { result: ItemImportOutcome }) {
  const { t } = useTranslation(["items"]);
  const anything =
    result.skipped > 0 ||
    result.created_locations.length > 0 ||
    result.created_categories.length > 0 ||
    result.created_suppliers.length > 0 ||
    result.brought_by_modules.length > 0 ||
    result.left_behind.length > 0;
  if (!anything) return null;
  return (
    <div className="bg-surface p-6 rounded-xl border border-border text-left max-w-md mx-auto space-y-3">
      {result.skipped > 0 && (
        <p className="text-xs text-on">
          {t("items:import.grocyMove.skipped", { count: result.skipped })}
        </p>
      )}
      <ImportFoundedList
        heading={t("items:import.foundedLocations", {
          count: result.created_locations.length,
        })}
        names={result.created_locations}
      />
      <ImportFoundedList
        heading={t("items:import.foundedCategories", {
          count: result.created_categories.length,
        })}
        names={result.created_categories}
      />
      <ImportFoundedList
        heading={t("items:import.grocyMove.foundedSuppliers", {
          count: result.created_suppliers.length,
        })}
        names={result.created_suppliers}
      />
      {/* What other modules brought from the same file, in their own
          words (the shopping lists, say). */}
      {result.brought_by_modules.map((brought) => (
        <p key={brought.module} className="text-xs text-on">
          {brought.sentence}
        </p>
      ))}
      <GrocyLeftBehindList entries={result.left_behind} />
    </div>
  );
}
