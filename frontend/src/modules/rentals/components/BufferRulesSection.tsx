import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2 } from "lucide-react";

import { Button, Input, NativeSelect, categoryLabel } from "@/module-sdk";

import type { BufferRule, CategoryOption, ModelOption } from "../api/rentals";

/** The hours an asset needs around a booking, set per model or category. */
export function BufferRulesSection({
  rules,
  models,
  categories,
  canWrite,
  onSave,
  onDelete,
}: {
  rules: BufferRule[] | undefined;
  models: ModelOption[];
  categories: CategoryOption[];
  canWrite: boolean;
  onSave: (data: {
    model?: string;
    category_id?: string;
    hours_before: number;
    hours_after: number;
  }) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation("rentals");
  const [target, setTarget] = useState<"model" | "category">("model");
  const [value, setValue] = useState("");
  const [before, setBefore] = useState(0);
  const [after, setAfter] = useState(4);

  useEffect(() => {
    if (target === "model" && !value && models.length) {
      setValue(models[0]?.model ?? "");
    }
  }, [target, value, models]);

  useEffect(() => {
    if (target === "category" && categories.length) {
      setValue(categories[0]?.id ?? "");
    }
  }, [target, categories]);

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <h2 className="border-b border-zinc-200 px-4 py-3.5 text-base font-semibold">
        {t("buffers.title")}
      </h2>
      <p className="px-4 py-2 text-sm text-zinc-500">{t("buffers.help")}</p>
      {(rules ?? []).length === 0 ? (
        <p className="px-4 py-2 text-sm text-zinc-500">{t("buffers.empty")}</p>
      ) : (
        (rules ?? []).map((rule) => {
          const ruleName =
            rule.model ??
            categoryLabel(t, rule.category_code, rule.category_name ?? "");
          return (
            <div
              key={rule.id}
              className="flex flex-wrap items-center gap-3 border-t border-zinc-100 px-4 py-2.5"
            >
              <span className="min-w-0 flex-1 text-sm">{ruleName}</span>
              <span className="text-sm text-zinc-600">
                {t("buffers.hours", {
                  before: rule.hours_before,
                  after: rule.hours_after,
                })}
              </span>
              <Button
                type="button"
                variant="ghostDanger"
                size="icon"
                aria-label={t("buffers.deleteNamed", { name: ruleName })}
                disabled={!canWrite}
                onClick={() => onDelete(rule.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          );
        })
      )}
      <div className="flex flex-wrap items-end gap-2 border-t border-zinc-100 px-4 py-3">
        <div className="w-36">
          <NativeSelect
            label={t("buffers.target")}
            value={target}
            onChange={(event) => {
              setTarget(event.target.value as "model" | "category");
              setValue("");
            }}
          >
            <option value="model">{t("buffers.model")}</option>
            <option value="category">{t("buffers.category")}</option>
          </NativeSelect>
        </div>
        <div className="min-w-0 flex-1 basis-40">
          <NativeSelect
            label={t("buffers.which")}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          >
            {target === "model"
              ? models.map((entry) => (
                  <option key={entry.model} value={entry.model}>
                    {entry.model}
                  </option>
                ))
              : categories.map((entry) => (
                  <option key={entry.id} value={entry.id}>
                    {categoryLabel(t, entry.code, entry.name)}
                  </option>
                ))}
          </NativeSelect>
        </div>
        <div className="w-24">
          <Input
            type="number"
            min={0}
            max={336}
            label={t("buffers.before")}
            value={before}
            onChange={(event) => setBefore(Number(event.target.value))}
          />
        </div>
        <div className="w-24">
          <Input
            type="number"
            min={0}
            max={336}
            label={t("buffers.after")}
            value={after}
            onChange={(event) => setAfter(Number(event.target.value))}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={!canWrite || !value}
          onClick={() =>
            onSave({
              model: target === "model" ? value : undefined,
              category_id: target === "category" ? value : undefined,
              hours_before: before,
              hours_after: after,
            })
          }
        >
          {t("buffers.save")}
        </Button>
      </div>
    </section>
  );
}
