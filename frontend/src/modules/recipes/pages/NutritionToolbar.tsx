import { Download, Plus, Upload } from "lucide-react";
import type { Ref } from "react";
import { Button } from "@/components/ui/Button";
import { ListControlBar } from "@/components/ui/ListControlBar";

interface NutritionToolbarProps {
  q: string;
  onSearch: (value: string) => void;
  onToggleAdd: () => void;
  onImport: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onExport: () => void;
  /** Lets an empty state open the import dialog: it holds no input of its
   *  own, so the toolbar lends it the one it has. */
  importInputRef?: Ref<HTMLInputElement>;
  /**
   * Whether the account may change the dictionary. False leaves the export
   * — the screen's read — standing alone.
   */
  canWrite: boolean;
  /**
   * False while the table has not been read.
   *
   * The reader takes "Export CSV" to mean "save what I am
   * looking at", and above an unread table there is nothing
   * to look at.
   */
  canExport: boolean;
  /**
   * Why the export is unavailable, when the reason is not "still loading":
   * an empty dictionary. Shows as the disabled button's tooltip, so a dead
   * button says what it is waiting for instead of just being dead.
   */
  exportHint?: string;
  t: (key: string) => string;
}

export function NutritionToolbar({
  q,
  onSearch,
  onToggleAdd,
  onImport,
  onExport,
  canWrite,
  canExport,
  exportHint,
  importInputRef,
  t,
}: NutritionToolbarProps) {
  return (
    <ListControlBar
      search={{
        value: q,
        onChange: onSearch,
        placeholder: t("recipes:ingredient_defaults.search_placeholder"),
      }}
      primaryAction={
        <>
          {canWrite && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onToggleAdd}
                className="gap-1"
              >
                <Plus size={16} />
                {t("recipes:ingredient_defaults.add")}
              </Button>
              <label className="inline-flex items-center justify-center gap-1 cursor-pointer h-8 px-3 text-xs font-medium rounded-lg border border-border bg-surface-card hover:bg-surface text-on-secondary transition-colors duration-200 select-none">
                <Upload size={15} />
                {t("recipes:ingredient_defaults.import")}
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".json,.csv"
                  className="hidden"
                  onChange={onImport}
                />
              </label>
            </>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={onExport}
            disabled={!canExport}
            title={exportHint}
            className="gap-1"
          >
            <Download size={16} />
            {t("recipes:ingredient_defaults.export")}
          </Button>
        </>
      }
    />
  );
}
