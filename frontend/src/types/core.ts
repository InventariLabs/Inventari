// Core / shared types used by multiple domains.
import type { components } from "./api-generated";

/**
 * AuditLog entry shape returned by GET /api/v1/audit-log.
 * Mirrors the backend AuditLogDTO. Mirrored locally because the
 * generated OpenAPI types in api-generated.ts predate the
 * endpoint addition; re-run `npm run generate-types` once the
 * backend stays still for a cycle.
 */
/**
 * @mirrors components["schemas"]["AuditLogDTO"]
 *
 * Checked against the generated schema by `npm run check:mirrors`. The
 * optional markers are the wire's: a field the backend may omit typed as
 * required here is a field every reader believes is always there.
 */
export interface AuditLogEntry {
  id: string;
  organization_id: string;
  user_id?: string | null;
  user_email?: string | null;
  action: string;
  target_type: string;
  target_id: string;
  snapshot?: Record<string, unknown> | null;
  reason?: string | null;
  meta_data?: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  /**
   * The journal stopped counting at `total` and holds more: the first page
   * counts only as far as the server's cap, and the cursor carries the flag on.
   */
  total_capped?: boolean;
  /** Hand it back as `cursor` for the page that follows; none on the last. */
  next_cursor?: string | null;
}

/**
 * What a custom field may be. Mirrors the `FieldType` literal in
 * `app/schemas/category.py`; a value not in that list is refused on save.
 * `uom_select` used to be here and was in neither the backend nor any
 * screen — a type nothing could produce and nothing would accept.
 */
export type FieldType =
  | "text"
  | "number"
  | "date"
  | "textarea"
  | "select"
  | "multi-select"
  | "boolean"
  | "file"
  | "money";

/**
 * A custom field definition, as the screens work with it.
 *
 * The wire shape is `components["schemas"]["CategoryFieldDefinition"]`
 * (the backend's own `app.schemas.category.CategoryFieldDefinition`); the frontend
 * intersects it with the markers the form builder and the seed add — so a
 * list straight off the wire and a list the form assembled are the same
 * type to a reader, and neither side drifts from the wire.
 */
export interface FieldDefinitionExtras {
  /** Set by the declaring module's seed — the label is platform copy,
   * resolvable in the reader's language (items:fields.<key>). */
  is_custom?: boolean;
  /** Input hint the form builder edits and the form renders; it travels
   * inside the wire's open field dicts, which do not declare it. */
  placeholder?: string | null;
  /** Context tags this field belongs to (e.g. ['food']). null = universal. */
  contexts?: string[] | null;
  /** For `date` fields: which relative jumps the picker offers. An expiry
   * date thinks in "in a month", a purchase date does not. */
  date_presets?: string[];
}

export type FieldDefinition = components["schemas"]["CategoryFieldDefinition"] &
  FieldDefinitionExtras;

// --- Unit of Measure ---

export type Uom = components["schemas"]["UomDTO"];

export type UomCategory = components["schemas"]["UomCategoryDTO"];

/**
 * The account, as `GET /auth/me` and every user listing answer.
 *
 * Taken from the schema rather than retyped: the hand-written copy carried
 * `organization_id`, which the backend's `User` model has never declared —
 * a field every reader of it was reading `undefined` off. The organization
 * comes from the organization context, not off the user.
 */
export type User = components["schemas"]["User"];

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface RegisterData {
  email: string;
  password: string;
  full_name?: string;
  invite_code?: string;
  preferred_language?: string;
}

/** A registration awaiting an administrator's decision (`GET /registrations`). */
export type RegistrationRequest = components["schemas"]["RegistrationRequest"];

export interface RegistrationCompleteData {
  token: string;
  password: string;
  full_name?: string;
  preferred_language?: string;
}

/**
 * The organization, as `GET /organizations/my` and the write endpoints
 * answer. Taken from the schema rather than retyped: the hand-written copy
 * carried `enabled_modules`, which this endpoint never sends — the shell
 * reads the module set from the modules endpoints, not off the org.
 */
export type Organization = components["schemas"]["Organization"];

/**
 * Where a module sits in the store's taxonomy. Declared by the module and
 * carried by `GET /modules/available` — the store used to read it off the
 * frontend launcher tile instead, which only tiled modules have.
 */
export type ModuleCategory =
  "core" | "business" | "analytics" | "integrations" | "system" | "other";

/**
 * The section a launcher tile sits in. Same taxonomy, minus the catch-all: a
 * tile always belongs to a named section, whereas a module the store has never
 * heard of has to land somewhere.
 */
export type LauncherCategory = Exclude<ModuleCategory, "other">;

/** A profile the store offers, as `GET /profiles` answers. */
export type ProductProfile = components["schemas"]["ProductProfile"];

/** Field-by-field what a profile switch would change (the dry run's answer). */
export type ProfileSwitchDiff =
  components["schemas"]["ProfileSwitchDiffResponse"];

export type ProfileSwitchResponse =
  components["schemas"]["ProfileSwitchResponse"];

export type ProfileSwitchRequest =
  components["schemas"]["ProfileSwitchRequest"];

/**
 * One row of the members list. Taken from the schema rather than retyped:
 * the hand-written copy carried `joined_at`, which the wire has never sent —
 * the hand-written body promised a column of dates no endpoint fills.
 */
export type OrganizationMember = components["schemas"]["OrganizationMember"];

// Module Types

/**
 * A module as the store lists it. Taken from the schema rather than
 * retyped: the schema carries `is_trusted`, `is_configured` and
 * `is_premium`, which the hand-written copy never declared, so screens
 * could not read what the endpoint was already sending.
 */
export type ModuleInfo = components["schemas"]["ModuleInfo"];
