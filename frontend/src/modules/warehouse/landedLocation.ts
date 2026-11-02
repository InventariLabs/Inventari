import type {
  DocumentLine,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/**
 * The shelf a line's goods went to, when it is not the one the document asked
 * for.
 *
 * A putaway rule can redirect a delivery: the document names Floor 2, the rule
 * says Floor 1, and the goods go to Floor 1. The document used to say nothing
 * about it, so the record, the ledger and the header each answered "where is
 * this" differently and only one of them was right.
 *
 * Returns `null` when the goods landed where the document said, which is the
 * ordinary case and needs no second sentence, and on a line a zone pinned to
 * the shelf it takes from: the executed place there is the shelf the goods
 * left, which the line already names as such.
 */
export function landedElsewhere(
  document: Pick<WarehouseDocument, "target_location_id">,
  line: Pick<
    DocumentLine,
    "executed_location_id" | "executed_location_name" | "source_location_id"
  >,
): string | null {
  if (!line.executed_location_id) return null;
  if (line.executed_location_id === document.target_location_id) return null;
  if (line.executed_location_id === line.source_location_id) return null;
  return line.executed_location_name ?? null;
}

/**
 * The shelf a receipt line's goods will land on, while they still wait.
 *
 * The backend computes this at read time with the same decision the executor
 * runs, so the sentence on the line and the booking it makes cannot disagree:
 * edit a rule and the next read says the new shelf. Returns `null` once the
 * line has executed — from then on `landedElsewhere` owns the story — and
 * for lines whose plan is the document's own target, which the header
 * already says.
 */
export interface PlannedPutaway {
  locationName: string;
  source: string;
  /** For a rule decision: the match key and the row it matched by, so the
   *  line can say "reguła: kategoria Farby" instead of a bare rule id. */
  ruleMatchKey: string | null;
  ruleMatchName: string | null;
  /** Set when a matching rule could not take the line — its target is
   *  archived or virtual — and the plan fell to the next source. */
  warning: string | null;
  /** The plan names a shelf that is already too full: goods still go
   *  there (they have arrived), and the numbers say by how much. */
  overCapacity: boolean;
  capacityUsed: string | null;
  capacityMax: string | null;
  /** The shelf's whole fill in percent, set when other products share it. */
  shelfFill: number | null;
}

export function plannedPutaway(
  line: Pick<
    DocumentLine,
    | "executed_location_id"
    | "planned_location_id"
    | "planned_location_name"
    | "planned_source"
    | "planned_rule_match_key"
    | "planned_rule_match_name"
    | "planned_rule_warning"
    | "planned_over_capacity"
    | "planned_capacity_used"
    | "planned_capacity_max"
    | "planned_shelf_fill"
  >,
): PlannedPutaway | null {
  if (line.executed_location_id) return null;
  // The document target is the header's own sentence; repeating it per line
  // says nothing the reader did not already read. The one exception is a
  // warning: a matched rule that had to step aside (archived or virtual
  // target) is exactly why the line fell back to the document, and that is
  // worth spelling out.
  if (line.planned_source === "document" && !line.planned_rule_warning) {
    return null;
  }
  if (!line.planned_location_id || !line.planned_location_name) return null;
  return toPlanned(line);
}

/** Shape the transport fields into the sentence's own vocabulary. */
function toPlanned(line: PlannedFields): PlannedPutaway {
  return {
    locationName: line.planned_location_name ?? "",
    source: line.planned_source ?? "document",
    ruleMatchKey: line.planned_rule_match_key ?? null,
    ruleMatchName: line.planned_rule_match_name ?? null,
    warning: line.planned_rule_warning ?? null,
    overCapacity: line.planned_over_capacity === true,
    capacityUsed: line.planned_capacity_used ?? null,
    capacityMax: line.planned_capacity_max ?? null,
    shelfFill: line.planned_shelf_fill ?? null,
  };
}

type PlannedFields = Pick<
  DocumentLine,
  | "planned_location_id"
  | "planned_location_name"
  | "planned_source"
  | "planned_rule_match_key"
  | "planned_rule_match_name"
  | "planned_rule_warning"
  | "planned_over_capacity"
  | "planned_capacity_used"
  | "planned_capacity_max"
  | "planned_shelf_fill"
>;

/**
 * The same plan, for a screen that has no header to lean on.
 *
 * ``plannedPutaway`` stays quiet when the plan is simply the document's own
 * target, because the office page prints that target at the top and a
 * per-line repetition says nothing. The WMS receiving screen prints it
 * nowhere: the worker holding the scanner sees rows and only rows. Staying
 * quiet there means the most ordinary delivery of all — no rule, no
 * override — is the one that arrives with no address on it.
 *
 * So the floor gets the shelf every time there is one. Same fields, same
 * planner, one suppression fewer.
 */
export function floorPutaway(line: PlannedFields): PlannedPutaway | null {
  if (!line.planned_location_id || !line.planned_location_name) return null;
  return toPlanned(line);
}
