import { useTranslation } from "react-i18next";
import { formatQuantityLocale } from "@/utils/formatters";
import type { PutawayPreviewLine } from "@/modules/warehouse/api/putaway";

/**
 * Why this line goes where it goes, in one sentence.
 *
 * The same vocabulary the saved document uses (`detail.planned*`), so a
 * reader who has seen the plan on a document reads this one without
 * learning a second phrasing. The only addition is the destination itself:
 * the document page prints it in the header, while this screen has no
 * header to lean on and must name it on every row.
 */
export function PutawayPlanSentence({
  plan,
  checking,
}: {
  plan: PutawayPreviewLine | undefined;
  checking: boolean;
}) {
  const { t } = useTranslation("warehouse");

  // No plan yet is the shelf select's own default option ("follow the
  // plan"); saying it again above the select pushed the select off the
  // row's line, so only the preview in flight is worth a line.
  if (!plan) {
    return checking ? (
      <span className="text-xs text-on-muted">
        {t("receive.plan.checking")}
      </span>
    ) : null;
  }
  if (!plan.planned_location_name) return null;
  const location = plan.planned_location_name;

  if (plan.planned_over_capacity && plan.planned_shelf_fill != null) {
    return (
      <span className="text-xs text-on-warning">
        {t("detail.plannedOverCapacityShared", {
          location,
          fill: plan.planned_shelf_fill,
        })}
      </span>
    );
  }
  if (plan.planned_over_capacity) {
    return (
      <span className="text-xs text-on-warning">
        {t("detail.plannedOverCapacity", {
          location,
          used: plan.planned_capacity_used
            ? formatQuantityLocale(plan.planned_capacity_used)
            : "—",
          max: plan.planned_capacity_max
            ? formatQuantityLocale(plan.planned_capacity_max)
            : "∞",
        })}
      </span>
    );
  }
  if (plan.planned_rule_warning) {
    return (
      <span className="text-xs text-on-warning">
        {t(`detail.plannedRuleWarning.${plan.planned_rule_warning}`, {
          rule:
            plan.planned_rule_match_name ?? t("detail.plannedRuleUnspecified"),
          location,
        })}
      </span>
    );
  }

  switch (plan.planned_source) {
    case "rule": {
      const keyLabel = plan.planned_rule_match_key
        ? t(`detail.ruleMatchKeys.${plan.planned_rule_match_key}`)
        : "";
      const match = [keyLabel, plan.planned_rule_match_name]
        .filter(Boolean)
        .join(" ");
      return (
        <span className="text-xs text-on-secondary">
          {t("detail.plannedByRule", {
            location,
            rule: match || t("detail.plannedRuleUnspecified"),
          })}
        </span>
      );
    }
    case "line":
      return (
        <span className="text-xs text-on-secondary">
          {t("detail.plannedByLine", { location })}
        </span>
      );
    case "serial":
      return (
        <span className="text-xs text-on-secondary">
          {t("detail.plannedBySerial", { location })}
        </span>
      );
    case "record":
      return (
        <span className="text-xs text-on-secondary">
          {t("detail.plannedByRecord", { location })}
        </span>
      );
    case "receiving":
      // Two-step receiving: the goods stop in the area and a putaway task
      // carries them on, so this is not the shelf they end up on.
      return (
        <span className="text-xs text-on-secondary">
          {t("detail.plannedReceiving", { location })}
        </span>
      );
    default:
      return (
        <span className="text-xs text-on-secondary">
          {t("receive.plan.destination", { location })}
        </span>
      );
  }
}
