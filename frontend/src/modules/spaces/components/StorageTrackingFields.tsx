/**
 * StorageTrackingFields — the "tracked fields" toggle list shared by the two
 * storage editor surfaces.
 *
 * `StorageEditSheet` renders the list as `solid` Button pairs; the `bordered`
 * variant (outlined chips) remains for callers that want the lighter chrome.
 * What the editors used to duplicate was this list: the same
 * `getNeutralBaseFields` → toggle → `context_schema` logic, written twice with
 * different chrome.
 *
 * `variant` keeps each site's chrome; the row geometry is shared — the
 * `solid` rows used to be 21px tall with a centred label.
 */
import { Check } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import {
  getNeutralBaseFields,
  NEUTRAL_BASE_FIELD_ICONS,
  type NeutralBaseFieldKey,
} from "@/modules/spaces/utils/neutralBaseFields";

interface StorageTrackingFieldsProps {
  /** Currently enabled field keys (the storage's `context_schema`). */
  value: string[];
  onChange: (next: string[]) => void;
  /**
   * Translator. Passed in rather than pulled from `useTranslation` so the
   * caller controls the namespace — both call sites default to `storages`,
   * and tests inject a `(key) => key` stub.
   */
  t: (key: string, opts?: Record<string, unknown>) => string;
  /**
   * `bordered` — outlined chips (default). Selection reads as
   * colour plus a tint, never as a heavier border: 2px changes the outer box
   * of the control and breaks its alignment with neighbours (§2.10).
   * `solid` — filled/outline Button pair (`StorageEditSheet`).
   *
   * The variant decides the chrome only. Geometry — padding, touch floor,
   * text alignment — is shared, because a row of this list is the same
   * control on both pages.
   */
  variant?: "bordered" | "solid";
  /**
   * Fields a location above already tracks. They apply here whatever this
   * location sets, so their rows are shown on and locked, naming the level
   * they come from; a field this location sets itself stays a toggle.
   */
  inherited?: Array<{ key: string; from_name: string }>;
}

export function StorageTrackingFields({
  value,
  onChange,
  t,
  variant = "bordered",
  inherited = [],
}: StorageTrackingFieldsProps) {
  // `getNeutralBaseFields` documents that its argument is a deliberate no-op
  // ("storage is now vertical-agnostic. Pass `undefined` to make the no-op
  // intent explicit"), so this component no longer threads a context tag it
  // cannot act on.
  const fields = getNeutralBaseFields(undefined);

  return (
    <div className="space-y-1.5">
      {fields.map((key) => {
        const fromAbove = value.includes(key)
          ? undefined
          : inherited.find((field) => field.key === key);
        const checked = value.includes(key) || fromAbove !== undefined;
        const Icon = NEUTRAL_BASE_FIELD_ICONS[key as NeutralBaseFieldKey];

        return (
          <Button
            size="content"
            key={key}
            type="button"
            variant={
              variant === "bordered"
                ? "ghost"
                : checked
                  ? "secondary"
                  : "outline"
            }
            disabled={fromAbove !== undefined}
            // The tick and the fill say "tracked" to the eye only.
            aria-pressed={checked}
            onClick={() =>
              onChange(
                checked ? value.filter((f) => f !== key) : [...value, key],
              )
            }
            className={cn(
              // `size="content"` leaves the height to the content, which for a
              // single line of text is 21px — below the 44px touch floor and
              // half the height of the controls this list sits between. The
              // padding and the floor therefore belong to the row, not to one
              // variant of it. `text-left` is here rather than on the label
              // span because `<button>` defaults to `text-align: center`, and
              // `justify-start` only places the flex children, not the text
              // inside a `flex-1` one.
              "w-full justify-start gap-3 px-3 py-2 min-h-11 md:min-h-10 text-left",
              // A field from above is locked, not unavailable: it applies
              // here, so its row keeps full contrast.
              "disabled:opacity-100",
              variant === "bordered" &&
                "rounded-xl border active:scale-100 " +
                  (checked
                    ? "border-primary-400 bg-primary-50 hover:bg-primary-50 active:bg-primary-50"
                    : "border-border bg-surface hover:bg-surface active:bg-surface"),
            )}
          >
            {Icon ? (
              <Icon
                size={16}
                className={`flex-shrink-0 ${
                  checked ? "text-on-primary" : "text-on-muted"
                }`}
              />
            ) : (
              <span className="w-5 text-center text-on-muted">·</span>
            )}
            <span
              className={`flex-1 text-sm font-semibold ${
                checked ? "text-on-primary" : "text-on-secondary"
              }`}
            >
              {t(`fieldLabels.${key}`, { defaultValue: key })}
            </span>
            {fromAbove && (
              <span className="text-xs font-normal text-on-muted">
                {t("locations:settings.inheritedFrom", {
                  name: fromAbove.from_name,
                })}
              </span>
            )}
            {checked && (
              <Check size={15} className="text-on-primary flex-shrink-0" />
            )}
          </Button>
        );
      })}
    </div>
  );
}
