import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import {
  useDocumentProfile,
  usePickOrderStrategies,
  useUpdateDocumentProfile,
} from "@/modules/warehouse/hooks/useDocumentProfile";
import { usePageSavePart } from "@/module-sdk";

/**
 * The walk a picking session takes through the warehouse: the default, or one
 * of the orders registered by modules (`register_pick_order_strategy`).
 *
 * Every entry is named from the catalogue of the module that registered it —
 * `<module>:pickOrderStrategies.<name>`, never the bare registry name — and
 * the default is stored as no choice at all, so a module switched off for the
 * organization costs the organization its walk and nothing more. The choice
 * waits for the page's Save with the rest of the profile.
 */
export function PickOrderSection() {
  const { t } = useTranslation("warehouse");
  const { data: profile } = useDocumentProfile();
  const {
    data: strategies = [],
    isError,
    error,
    refetch,
  } = usePickOrderStrategies();
  const updateMutation = useUpdateDocumentProfile();

  // The default leads: it is the walk an organization is on until it chooses.
  const ordered = [
    ...strategies.filter((entry) => entry.is_default),
    ...strategies.filter((entry) => !entry.is_default),
  ];
  const defaultName = strategies.find((entry) => entry.is_default)?.name ?? "";
  const stored = profile?.pick_order_strategy || defaultName;
  // The pick waits for the page's Save; `null` is "not touched".
  const [choice, setChoice] = useState<string | null>(null);
  const selected = choice ?? stored;

  const save = async () => {
    if (choice === null) return;
    await updateMutation.mutateAsync({
      pick_order_strategy: choice === defaultName ? null : choice,
    });
    setChoice(null);
  };
  usePageSavePart("pickOrder", choice !== null && choice !== stored, save);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-sm font-semibold text-on">
          {t("profile.pickOrderStrategy")}
        </h2>
        <p className="text-xs text-on-muted mt-1">
          {t("profile.pickOrderStrategyHint")}
        </p>
      </div>
      <div className="space-y-1.5 max-w-md">
        <NativeSelect
          id="profile-pick-order-strategy"
          aria-label={t("profile.pickOrderStrategy")}
          value={selected}
          onChange={(event) => setChoice(event.target.value)}
        >
          {ordered.map((entry) => (
            <option key={entry.name} value={entry.name}>
              {t(entry.label_key, { defaultValue: entry.name })}
            </option>
          ))}
        </NativeSelect>
        {isError && (
          <InlineQueryError error={error} onRetry={() => refetch()} />
        )}
      </div>
    </section>
  );
}
