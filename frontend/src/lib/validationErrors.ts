/**
 * Map an API 4xx response `detail` to a flat field/line error map so the
 * frontend can render per-field inline errors.
 *
 * Supports three wire shapes produced by the backend:
 *
 * 1. FastAPI / Pydantic request validation (HTTP 422):
 *    `{ "detail": [ { "loc": [...], "msg": "...", "type": "..." }, ... ] }`
 * 2. `ValidationException` (HTTP 400) with structured detail:
 *    `{ "detail": { "code": "VALIDATION_ERROR", "message": "...", "field": "?" } }`
 * 3. Plain string detail:
 *    `{ "detail": "Something failed" }`
 *
 * The returned record uses the same flat keys the documents workspace
 * validator uses, so the modal can merge API and client errors into one
 * `errors` state:
 *   - top-level: `partner_id`, `source_location_id`, `target_location_id`,
 *     `notes`, `external_reference`, `scheduled_date`
 *   - per-line: `line.<stableKey>.name`, `line.<stableKey>.quantity`
 *   - fallback: `_form` (rendered by the caller as a form-level message)
 *
 * Line indices from the backend are translated to the frontend's stable
 * line keys via `indexToKey`. When the index can't be resolved, the numeric
 * index is used as a degraded fallback so the error is still preserved in
 * the record (callers may choose to ignore unmatched keys).
 */

const BODY_FIELD_KEYS = new Set([
  "partner_id",
  "source_location_id",
  "target_location_id",
  "notes",
  "external_reference",
  "scheduled_date",
]);

const LINE_QUANTITY_FIELDS = new Set(["quantity", "expected_quantity"]);
const LINE_NAME_FIELDS = new Set(["name", "item_id", "product_template_id"]);

type LineIndexToKey = (lineIndex: number) => string | undefined;

export function parseApiValidationErrors(
  detail: unknown,
  indexToKey: LineIndexToKey,
): Record<string, string> {
  if (Array.isArray(detail)) {
    return parseArray(detail, indexToKey);
  }
  if (detail && typeof detail === "object") {
    return parseStructured(detail as Record<string, unknown>);
  }
  if (typeof detail === "string") {
    return { _form: detail };
  }
  return {};
}

function parseArray(
  detail: unknown[],
  indexToKey: LineIndexToKey,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const entry of detail) {
    if (!entry || typeof entry !== "object") continue;
    const loc = (entry as { loc?: unknown }).loc;
    const msg = (entry as { msg?: unknown }).msg;
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const key = mapLocToKey(loc, indexToKey);
    if (key) errors[key] = msg;
  }
  return errors;
}

function mapLocToKey(
  loc: unknown[],
  indexToKey: LineIndexToKey,
): string | null {
  // Strip leading "body".
  const path = loc[0] === "body" ? loc.slice(1) : loc;

  // [""] / ["body"] -> _form
  if (path.length === 0) return "_form";

  // ["lines"] (min_length on the array) -> _form
  if (path.length === 1 && path[0] === "lines") return "_form";

  // ["lines", i, field?]
  if (path[0] === "lines" && typeof path[1] === "number") {
    const lineIndex = path[1];
    const stableKey = indexToKey(lineIndex) ?? String(lineIndex);
    if (path.length === 2) {
      // Line-object model error (e.g. identity validator) — no specific
      // field to attribute it to. Bucket to the form-level fallback so the
      // message is preserved (callers may surface it as a form-level alert).
      return "_form";
    }
    const field = String(path[2]);
    if (LINE_QUANTITY_FIELDS.has(field)) {
      return `line.${stableKey}.quantity`;
    }
    if (LINE_NAME_FIELDS.has(field)) {
      return `line.${stableKey}.name`;
    }
    return "_form";
  }

  // Known top-level body fields -> their own key.
  if (path.length === 1 && typeof path[0] === "string") {
    if (BODY_FIELD_KEYS.has(path[0])) return path[0];
  }

  // Everything else (unknown top-level fields, nested paths) -> _form.
  return "_form";
}

function parseStructured(
  detail: Record<string, unknown>,
): Record<string, string> {
  const message = typeof detail.message === "string" ? detail.message : null;
  if (!message) return {};
  const field = typeof detail.field === "string" ? detail.field : null;
  if (field && BODY_FIELD_KEYS.has(field)) {
    return { [field]: message };
  }
  return { _form: message };
}
