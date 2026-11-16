import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tag } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/module-sdk";
import { Input } from "@/components/ui/Input";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useCanManage } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { useWhereUsed } from "@/modules/maker/hooks/useBom";
import {
  useLabelFacts,
  useSetLabelFacts,
} from "@/modules/maker/hooks/useLabelling";
import {
  ALLERGEN_KEYS,
  type AllergenKey,
  useAllergenName,
} from "@/modules/maker/lib/allergens";
import type {
  LabelAllergen,
  LabelFacts,
  LabelFactsUpdate,
} from "@/modules/maker/types/maker";
import type { Item } from "@/types";

interface LabelFactsSlotProps {
  data?: { item?: Item };
}

function asUpdate(facts: LabelFacts): LabelFactsUpdate {
  return {
    label_name: facts.label_name,
    allergens: facts.allergens,
    may_contain: facts.may_contain,
  };
}

function toggled(list: AllergenKey[], key: AllergenKey): AllergenKey[] {
  return list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
}

/** Fourteen checkboxes for one list: what the product contains, or may. */
function AllergenChoice({
  legend,
  value,
  disabled,
  onToggle,
}: {
  legend: string;
  value: AllergenKey[];
  disabled: boolean;
  onToggle: (key: AllergenKey) => void;
}) {
  const name = useAllergenName();
  const id = useId();
  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-medium uppercase text-on-secondary tracking-wide ml-1">
        {legend}
      </legend>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-3 gap-y-1">
        {ALLERGEN_KEYS.map((key) => (
          <Checkbox
            key={key}
            id={`${id}-${key}`}
            label={name(key)}
            checked={value.includes(key)}
            disabled={disabled}
            onChange={() => onToggle(key)}
          />
        ))}
      </div>
    </fieldset>
  );
}

/** The allergens a made product's recipe brings, each with its ingredients. */
export function DerivedAllergens({
  entries,
  testId,
}: {
  entries: LabelAllergen[];
  testId: string;
}) {
  const { t } = useTranslation("maker");
  const name = useAllergenName();
  return (
    <ul className="space-y-0.5 text-sm" data-testid={testId}>
      {entries.map((entry) => (
        <li key={entry.allergen} className="text-on-secondary">
          <span className="font-medium text-on">{name(entry.allergen)}</span>
          {entry.sources.length > 0 && (
            <>
              {" — "}
              {t("labelling.from", {
                names: entry.sources.map((s) => s.name).join(", "),
              })}
            </>
          )}
          {entry.declared_on_product && (
            <span className="text-on-muted">
              {entry.sources.length > 0 ? "; " : " — "}
              {t("labelling.declaredOnProduct")}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** What the card says of the allergens, in one line, with the way to check them. */
function AllergenSummary({
  facts,
  canManage,
  onSave,
  onEdit,
}: {
  facts: LabelFacts;
  canManage: boolean;
  onSave: (update: Partial<LabelFactsUpdate>) => void;
  onEdit: () => void;
}) {
  const { t } = useTranslation("maker");
  const name = useAllergenName();
  const names = (keys: string[]) => keys.map(name).join(", ");
  // A made product's allergens come from its BOM; what its own card adds is
  // a declaration on top, which nobody owes before the product can be made.
  const made = Boolean(facts.recipe_id);
  if (!made && (facts.allergens === null || facts.allergens === undefined)) {
    const suggested = facts.suggested_allergens;
    return (
      <div className="space-y-2" data-testid="maker-label-unchecked">
        <p className="text-sm text-on-warning">
          {t("labelling.card.unchecked")}
          {suggested.length > 0 &&
            ` ${t("labelling.card.suggested", { allergens: names(suggested) })}`}
        </p>
        {canManage && (
          <div className="flex flex-wrap gap-2">
            {suggested.length > 0 && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => onSave({ allergens: suggested })}
                data-testid="maker-label-confirm-suggestion"
              >
                {t("labelling.card.confirmSuggestion")}
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => onSave({ allergens: [] })}
              data-testid="maker-label-contains-none"
            >
              {t("labelling.card.containsNone")}
            </Button>
            <Button size="sm" variant="ghost" onClick={onEdit}>
              {t("labelling.card.choose")}
            </Button>
          </div>
        )}
      </div>
    );
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm items-baseline">
      <dt className="text-on-muted">
        {made ? t("labelling.card.ownAllergens") : t("labelling.contains")}
      </dt>
      <dd className="text-on" data-testid="maker-label-contains">
        {facts.allergens && facts.allergens.length > 0
          ? names(facts.allergens)
          : t("labelling.card.none")}
      </dd>
      <dt className="text-on-muted">{t("labelling.mayContain")}</dt>
      <dd className="text-on" data-testid="maker-label-may-contain">
        {facts.may_contain.length > 0
          ? names(facts.may_contain)
          : t("labelling.card.none")}
      </dd>
      {canManage && (
        <dd className="col-start-2">
          <Button
            size="inline"
            variant="link"
            onClick={onEdit}
            data-testid="maker-label-edit"
          >
            {t("labelling.card.change")}
          </Button>
        </dd>
      )}
    </dl>
  );
}

/** The section's heading over a read that failed, with its retry. */
function LabelReadFailed({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const { t } = useTranslation("maker");
  return (
    <section className="mt-3 space-y-1.5" data-testid="maker-label-facts">
      <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-on-muted font-medium">
        <Tag size={13} aria-hidden="true" />
        {t("labelling.card.title")}
      </h4>
      <InlineQueryError error={error} onRetry={onRetry} />
    </section>
  );
}

/** Whether the card has a label to speak of: a made product, one a BOM
 *  uses, or one that already has facts. */
function hasLabel(facts: LabelFacts, usedIn: number): boolean {
  return (
    Boolean(facts.recipe_id) ||
    usedIn > 0 ||
    facts.allergens != null ||
    facts.may_contain.length > 0 ||
    Boolean(facts.label_name)
  );
}

/** Both lists as checkboxes, saved as each is ticked. */
function AllergenEditor({
  facts,
  disabled,
  onSave,
  onDone,
}: {
  facts: LabelFacts;
  disabled: boolean;
  onSave: (change: Partial<LabelFactsUpdate>) => void;
  onDone: () => void;
}) {
  const { t } = useTranslation("maker");
  const contains = facts.allergens ?? [];
  return (
    <div className="space-y-3">
      <AllergenChoice
        legend={
          facts.recipe_id
            ? t("labelling.card.ownAllergens")
            : t("labelling.contains")
        }
        value={contains}
        disabled={disabled}
        onToggle={(key) => onSave({ allergens: toggled(contains, key) })}
      />
      <AllergenChoice
        legend={t("labelling.mayContain")}
        value={facts.may_contain}
        disabled={disabled}
        onToggle={(key) =>
          onSave({ may_contain: toggled(facts.may_contain, key) })
        }
      />
      <Button size="sm" variant="outline" onClick={onDone}>
        {t("labelling.card.done")}
      </Button>
    </div>
  );
}

/** A made product's allergens as its BOM brings them, and whose they are. */
function FromRecipe({ facts }: { facts: LabelFacts }) {
  const { t } = useTranslation("maker");
  if (!facts.recipe_id) return null;
  const derived = facts.derived_allergens ?? [];
  return (
    <>
      {derived.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase text-on-secondary tracking-wide ml-1">
            {t("labelling.card.fromRecipe")}
          </p>
          <DerivedAllergens entries={derived} testId="maker-label-derived" />
        </div>
      )}
      <p className="text-xs text-on-muted">{t("labelling.computedNote")}</p>
    </>
  );
}

/**
 * What a product's label says of it, on its card: the name it goes under in
 * an ingredient list, the allergens a person confirmed, what it may contain,
 * and — for a made product — the allergens its recipe brings, each with the
 * ingredients that bring it.
 *
 * The facts are the maker module's own record, saved as they change — the
 * card's Save writes the product's Core fields only, as the shelf life does.
 * Shown for a product that is made, goes into a formula or already has
 * facts; a product no formula touches has no list to be in.
 */
export function LabelFactsSlot({ data }: LabelFactsSlotProps) {
  const { t } = useTranslation("maker");
  const canManage = useCanManage("maker");
  const templateId = data?.item?.template_id ?? null;
  const factsQuery = useLabelFacts(templateId);
  const whereUsedQuery = useWhereUsed(templateId ?? undefined);
  const { data: facts } = factsQuery;
  const { data: whereUsed, isError: whereUsedFailed } = whereUsedQuery;
  const save = useSetLabelFacts(templateId ?? "");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const savedName = facts?.label_name ?? "";
  useEffect(() => setName(savedName), [savedName]);

  if (!templateId) return null;
  // Nothing rendered means "no label to speak of"; a failed read must not
  // pass for it, so it says the answer is missing.
  if (factsQuery.isError || whereUsedFailed) {
    return (
      <LabelReadFailed
        error={factsQuery.error ?? whereUsedQuery.error}
        onRetry={() => {
          void factsQuery.refetch();
          void whereUsedQuery.refetch();
        }}
      />
    );
  }
  if (!facts) return null;
  if (!hasLabel(facts, whereUsed?.items.length ?? 0)) return null;

  const commit = async (change: Partial<LabelFactsUpdate>) => {
    try {
      await save.mutateAsync({ ...asUpdate(facts), ...change });
      toast.success(t("labelling.card.saved"));
    } catch (error) {
      toast.error(extractApiError(error, t("labelling.card.saveFailed")));
    }
  };
  const disabled = !canManage || save.isPending;

  return (
    <section className="mt-3 space-y-3" data-testid="maker-label-facts">
      <h4 className="flex items-center gap-1.5 text-xs uppercase tracking-widest text-on-muted font-medium">
        <Tag size={13} aria-hidden="true" />
        {t("labelling.card.title")}
      </h4>
      <Input
        label={t("labelling.card.labelName")}
        description={t("labelling.card.labelNameHint")}
        value={name}
        maxLength={255}
        placeholder={data?.item?.template?.name ?? undefined}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => {
          if (name.trim() !== savedName) void commit({ label_name: name });
        }}
        disabled={disabled}
        data-testid="maker-label-name-input"
      />
      {editing ? (
        <AllergenEditor
          facts={facts}
          disabled={disabled}
          onSave={(change) => void commit(change)}
          onDone={() => setEditing(false)}
        />
      ) : (
        <AllergenSummary
          facts={facts}
          canManage={canManage}
          onSave={(change) => void commit(change)}
          onEdit={() => setEditing(true)}
        />
      )}
      <FromRecipe facts={facts} />
    </section>
  );
}

export default LabelFactsSlot;
