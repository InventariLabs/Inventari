import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { QrCode, Loader2, X, ChevronDown, Plus } from "lucide-react";
import { useLabels, useGenerateLabels } from "@/modules/shared/hooks/useLabels";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { InlineQueryError } from "@/components/ui/QueryResult";
import type { LabelPool } from "@/types";

interface LabelPickerInputProps {
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
  /** Element id for the trigger button — lets a form label associate. */
  id?: string;
}

/**
 * Generic label picker — lets the user pick an existing unassigned label
 * from the pool or generate a new one on the fly.
 * Lives in shared because the labels API is Core and both equipment and
 * printing render it; neither module owns it.
 */
export function LabelPickerInput({
  value,
  onChange,
  disabled,
  id,
}: LabelPickerInputProps) {
  const { t } = useTranslation("equipment");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const generateMutation = useGenerateLabels();

  const { data, isLoading, isError, error, refetch } = useLabels(true); // unassigned only
  const labels = data?.items ?? [];

  const filtered = search.trim()
    ? labels.filter(
        (l) =>
          l.short_code.toLowerCase().includes(search.toLowerCase()) ||
          (l.description ?? "").toLowerCase().includes(search.toLowerCase()),
      )
    : labels;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // `mutate`: the button awaits nothing, so a refused generate is read only
  // through the factory's toast.
  const handleGenerate = () => {
    generateMutation.mutate(
      { count: 1, label_type: "ITEM" },
      {
        onSuccess: (result) => {
          if (result[0]) onChange(result[0].short_code);
        },
      },
    );
  };

  const handleSelect = (label: LabelPool) => {
    onChange(label.short_code);
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="relative" ref={containerRef}>
      <div className="flex gap-2">
        {/* Current value display */}
        <Button
          type="button"
          id={id}
          disabled={disabled}
          onClick={() => setOpen((v) => !v)}
          variant="outline"
          size="contentSm"
          className="flex-1 h-auto min-h-[38px] px-3 py-2 justify-start text-left gap-2 hover:border-primary-400 hover:bg-surface-card"
        >
          {value ? (
            <>
              <QrCode size={14} className="text-accent-500 shrink-0" />
              <span className="font-mono text-sm text-on flex-1">{value}</span>
              {!disabled && (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    onChange("");
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.stopPropagation();
                      onChange("");
                    }
                  }}
                  className="text-on-muted hover:text-on p-0.5 rounded"
                  title={t("form.labels.clear", "Clear label")}
                >
                  <X size={14} />
                </span>
              )}
            </>
          ) : (
            <>
              <span className="text-sm text-on-muted">
                {t("form.labels.noLabel", "No label assigned")}
              </span>
              <ChevronDown
                size={14}
                className={`ml-auto text-on-muted transition-transform ${open ? "rotate-180" : ""}`}
              />
            </>
          )}
        </Button>

        {/* Generate new */}
        <Button
          type="button"
          variant="outline"
          size="icon"
          disabled={disabled || generateMutation.isPending}
          onClick={handleGenerate}
          title={t("form.labels.generateNew", "Generate new label")}
          aria-label={t("form.labels.generateNew", "Generate new label")}
        >
          {generateMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Plus size={16} />
          )}
        </Button>
      </div>

      {/* Pool dropdown */}
      {open && (
        <div className="absolute z-50 top-full mt-1 left-0 right-0 bg-surface-card border border-border rounded-xl shadow-xl overflow-hidden">
          <div className="p-2 border-b border-border">
            <Input
              autoFocus
              aria-label={t("form.labels.searchPool", "Search labels…")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("form.labels.searchPool", "Search labels…")}
              className="bg-surface-raised border-0 shadow-none"
            />
          </div>
          <div className="max-h-52 overflow-y-auto">
            {isLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 size={18} className="animate-spin text-on-muted" />
              </div>
            ) : isError ? (
              <div className="p-3">
                <InlineQueryError
                  error={error}
                  onRetry={() => void refetch()}
                />
              </div>
            ) : filtered.length === 0 ? (
              <p className="text-sm text-on-muted text-center py-4 px-4">
                {t("form.labels.emptyPool", "No free labels in pool")}
              </p>
            ) : (
              filtered.map((label) => (
                <Button
                  key={label.id}
                  variant="ghost"
                  size="sm"
                  onClick={() => handleSelect(label)}
                  className="w-full justify-start gap-3 px-4 py-2.5"
                >
                  <QrCode size={14} className="text-on-muted shrink-0" />
                  <span className="font-mono text-sm text-on">
                    {label.short_code}
                  </span>
                  {label.description && (
                    <span className="text-xs text-on-muted ml-auto truncate max-w-[140px]">
                      {label.description}
                    </span>
                  )}
                </Button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
