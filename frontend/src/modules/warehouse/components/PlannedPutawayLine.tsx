import { useTranslation } from "react-i18next";
import { formatQuantityLocale } from "@/utils/formatters";
import { plannedPutaway } from "@/modules/warehouse/landedLocation";
import type { DocumentLine } from "@/modules/warehouse/types";

/**
 * The putaway sentence on a line that still waits for execution:
 * "→ A-12 · reguła: kategoria Farby".
 *
 * A decision the worker cannot see before it books is a decision they cannot
 * correct — this is the read-side half of making the rule's choice visible
 * (the executor was already following it). After execution the component
 * steps aside; `landedElsewhere` owns the story from there.
 */
export function PlannedPutawayLine({ line }: { line: DocumentLine }) {
  const { t } = useTranslation("warehouse");
  const planned = plannedPutaway(line);
  if (!planned) return null;

  // An over-full shelf is the headline: the goods still go there (they
  // have arrived), and the numbers say by how much the shelf is over. On a
  // shelf other products share, that is the sum of their shares: this
  // product's own pair can look roomy on a shelf that is full.
  if (planned.overCapacity && planned.shelfFill !== null) {
    return (
      <p className="text-xs text-amber-700">
        {t("detail.plannedOverCapacityShared", {
          location: planned.locationName,
          fill: planned.shelfFill,
        })}
      </p>
    );
  }
  if (planned.overCapacity) {
    return (
      <p className="text-xs text-amber-700">
        {t("detail.plannedOverCapacity", {
          location: planned.locationName,
          used: planned.capacityUsed
            ? formatQuantityLocale(planned.capacityUsed)
            : "—",
          max: planned.capacityMax
            ? formatQuantityLocale(planned.capacityMax)
            : "∞",
        })}
      </p>
    );
  }

  // The warning is the sentence: a matched rule that had to step aside is
  // the one thing the reader must not miss about this plan. It still has to
  // end with the shelf the line will actually reach — the sentence used to
  // drop it, leaving the reader knowing why the rule lost and not where the
  // goods go, which is the question they opened the line to answer.
  if (planned.warning) {
    return (
      <p className="text-xs text-amber-700">
        {t(`detail.plannedRuleWarning.${planned.warning}`, {
          rule: planned.ruleMatchName ?? t("detail.plannedRuleUnspecified"),
          location: planned.locationName ?? "—",
        })}
      </p>
    );
  }

  const sentence = (() => {
    switch (planned.source) {
      case "rule": {
        // The match key is a word the reader translates; the match name is
        // data. "kategoria Farby" assembles here, per locale.
        const keyLabel = planned.ruleMatchKey
          ? t(`detail.ruleMatchKeys.${planned.ruleMatchKey}`)
          : "";
        const match = [keyLabel, planned.ruleMatchName]
          .filter(Boolean)
          .join(" ");
        return t("detail.plannedByRule", {
          location: planned.locationName,
          rule: match || t("detail.plannedRuleUnspecified"),
        });
      }
      case "line":
        return t("detail.plannedByLine", {
          location: planned.locationName,
        });
      case "serial":
        return t("detail.plannedBySerial", {
          location: planned.locationName,
        });
      case "record":
        return t("detail.plannedByRecord", {
          location: planned.locationName,
        });
      case "receiving":
        return t("detail.plannedReceiving", {
          location: planned.locationName,
        });
      default:
        return t("detail.plannedByRule", {
          location: planned.locationName,
          rule: planned.ruleMatchName ?? t("detail.plannedRuleUnspecified"),
        });
    }
  })();

  return <p className="text-xs text-on-secondary">{sentence}</p>;
}
