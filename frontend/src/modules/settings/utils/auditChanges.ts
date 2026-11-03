import { categoryLabel } from "@/lib/i18nHelpers";
import {
  formatDate,
  formatDateTime,
  formatQuantityLocale,
} from "@/utils/formatters";
import type { TranslateFn } from "@/types/i18n";

/** One leaf that moved, named by the path it sits at. */
export interface AuditChange {
  /** Dotted path inside the snapshot, e.g. `meta_data.nutrition.fat`. */
  path: string;
  /** How it read before — null for a CREATE, which has no before. */
  from: string | null;
  to: string;
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * A date or a timestamp, written the way the backend writes them.
 *
 * Deliberately narrow: `2026` parses as a date and is a number, and
 * `2026-09` is a period, not a day somebody picked. `Date.parse` has to
 * agree as well — the pattern alone accepts `2026-13-45`.
 */
const ISO_DATE_TIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$/;

/** A code the backend chose — `ALL`, `STORAGE`, `PENDING_RETRY`. */
const ENUM_CODE_PATTERN = /^[A-Z][A-Z0-9_]*$/;

/**
 * A decimal the database serialised as text — `2.000`, `-0.500`.
 *
 * A Decimal column crosses the wire as a string, so the journal printed half
 * a row in the reader's numbers (`0`) and half in the store's scale
 * (`2.000`). A whole number arrives as a JSON number, which keeps its own
 * branch; this one catches what the scale added.
 */
const DECIMAL_STRING_PATTERN = /^-?\d+\.\d+$/;

/**
 * How deep the walk goes before a value is printed as JSON.
 *
 * A product's `meta_data` from a food database nests three levels, and past
 * that a path stops being something a reader can hold in their head.
 */
const MAX_DEPTH = 4;

/**
 * The keys a snapshot uses to say which record it is about.
 *
 * Most records are known by a name. A document and a purchase order are known
 * by their number and write it under `number`, never under `name`. Both are
 * the Target column's answer, so neither is also a change line.
 */
const IDENTITY_KEYS = ["name", "number"] as const;

/**
 * The key an update's snapshot uses to say which fields moved.
 *
 * The list is written in field names, not values — `fields: ["brand"]` —
 * so its elements read through the same catalogue the change lines' keys do:
 * a writer that named the field, the reader can name too. A field no
 * catalogue carries stays raw, exactly as that field's own line would; with
 * no translator the list reads as it was written.
 */
const FIELDS_KEY = "fields";

/** The approval entry's own target descriptor (`{type, id, number}`). */
const APPROVAL_TARGET_KEY = "approves";

/**
 * How a snapshot names its own record, or null when it does not.
 *
 * The identity is already in the record: reading it costs no query, which is
 * what a journal cannot afford per row.
 */
export function snapshotIdentity(snapshot: unknown): string | null {
  if (!isPlainObject(snapshot)) return null;
  for (const key of IDENTITY_KEYS) {
    const value = snapshot[key];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return null;
}

/** A name for an id, when the page already knows one.
 *
 * *kind* is the reference the field names — `organization` for
 * `organization_id`, `storage_location` for `storage_location_id`, and
 * nothing at all for a value that is not a reference. A caller that can say
 * which kind it is asking about gets the name that belongs to that kind, and
 * a caller that cannot says so, rather than taking whatever the page holds.
 */
export type IdResolver = (uuid: string, kind?: string) => string | null;

/**
 * The journal's name for the kind a snapshot field names.
 *
 * The two vocabularies were written apart: a field says
 * `storage_location_id` while the row about that shelf is typed `storage`,
 * and a field says `template_id` against `product_template`. Everything else
 * is spelled the same on both sides, which is why this table holds the
 * exceptions and not the rule.
 */
const REFERENCE_TARGET_TYPES: Record<string, string> = {
  storage_location: "storage",
  template: "product_template",
  profile: "product_profile",
  user: "org_member",
};

export function referenceTargetType(kind: string): string {
  return REFERENCE_TARGET_TYPES[kind] ?? kind;
}

/**
 * The reference kind a field names, when it names one.
 *
 * `organization_id` names an organization; `reason` names nothing that can be
 * looked up. The kind travels with the id to the resolver so that a name can
 * only ever come from a row of the kind the field asked about.
 */
function referenceKindOf(path: string): string | undefined {
  const field = path.split(".").pop() ?? "";
  return field.endsWith(REFERENCE_ID_SUFFIX) &&
    field.length > REFERENCE_ID_SUFFIX.length
    ? field.slice(0, -REFERENCE_ID_SUFFIX.length)
    : undefined;
}

const REFERENCE_ID_SUFFIX = "_id";
const REFERENCE_NAME_SUFFIX = "_name";
const REFERENCE_CODE_SUFFIX = "_code";

/**
 * The references the app names by code, keyed by the reference's base.
 *
 * A seeded category is stored under its seed's English (`Dairy`) and read by
 * every screen through the code it carries. A journal that prints the record's
 * own name answers with a word the product screen never uses — one category,
 * one name — so when the snapshot carries the code, the label comes from the
 * same resolver the rest of the app reads it through.
 */
const REFERENCE_CODE_RESOLVERS: Record<
  string,
  (t: TranslateFn, code: string, name: string) => string
> = {
  category: categoryLabel,
};

/** True for the readings a value takes when there is nothing there. */
function isEmptyValue(text: string): boolean {
  return text === "" || text === "—";
}

/**
 * The name the snapshot hung beside a reference id, when it hung one there.
 *
 * A journal row that says `Location: 67d57628` answers nothing the reader
 * asked: the snapshot carries the name the record had when the change was
 * written, because the row it points at can be renamed afterwards. That name
 * is the id's label, not a change of its own. Where the snapshot also carries
 * the reference's code and the app reads that reference by code, the code's
 * label wins — and a code no catalogue knows falls back to the name written
 * down, then to the shortened id.
 */
function referenceNameOf(
  container: Record<string, unknown>,
  key: string,
  t?: TranslateFn,
): string | null {
  if (!key.endsWith(REFERENCE_ID_SUFFIX)) return null;
  const base = key.slice(0, -REFERENCE_ID_SUFFIX.length);
  const name = container[`${base}${REFERENCE_NAME_SUFFIX}`];
  const recorded = typeof name === "string" && name.trim() !== "" ? name : null;
  const resolver = REFERENCE_CODE_RESOLVERS[base];
  const code = container[`${base}${REFERENCE_CODE_SUFFIX}`];
  if (t && resolver && typeof code === "string" && code.trim() !== "") {
    const label = resolver(t, code, "");
    if (label) return label;
  }
  return recorded;
}

/** True when `key` is a label written for a reference id beside it. */
function isReferenceLabel(
  key: string,
  container: Record<string, unknown>,
): boolean {
  for (const suffix of [REFERENCE_NAME_SUFFIX, REFERENCE_CODE_SUFFIX]) {
    if (!key.endsWith(suffix)) continue;
    const base = key.slice(0, -suffix.length);
    if (`${base}${REFERENCE_ID_SUFFIX}` in container) return true;
  }
  return false;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.getPrototypeOf(value) === Object.prototype
  );
}

/**
 * One side of a change as a record to walk into, or null when it is not one.
 *
 * Nothing at all is an empty record: the two sides of a field that just
 * appeared have to be the same shape for the walk to name the fields instead
 * of printing the whole value. Anything that is neither an object nor absent
 * stays null — an array beside a record is a value, not a pair to descend.
 */
function absentAsEmpty(value: unknown): Record<string, unknown> | null {
  if (isPlainObject(value)) return value;
  return value === null || value === undefined ? {} : null;
}

/**
 * A value as the journal shows it.
 *
 * Floats are rounded. A nutrition figure stored as a 32-bit float reads back
 * as `1.7999999523162842`, and eighteen digits of a rounding artefact is not
 * something anybody meant to record. The value in the data — and in the CSV
 * export, which writes the snapshot itself — is untouched.
 *
 * A timestamp is formatted, not printed. The backend writes dates as ISO
 * (`deadline: 2026-09-25T23:59:59.999999+00:00`), and that string used to
 * reach the reader exactly as written — microseconds, offset and all — in a
 * column whose every other row says `18.09.2026, 14:41`. The same formatter
 * the column beside it uses, so one date has one spelling on one screen.
 *
 * A value in capitals is a code the backend chose, and it goes through the
 * catalogue before it is printed: `Scope type: ALL` reads `Typ zakresu:
 * Wszystkie`, and `Nowy status: CONFIRMED` reads `Potwierdzone` — the word
 * the record's own list shows, in the same catalogue the other codes read.
 * One code carries one word: a completed order and a closed attestation
 * spell their close differently in some languages, and the row names the
 * record, so the reader is not left guessing which one it is. Only when the
 * catalogue has no word — an unlisted code stays as it arrived, which is
 * where it was before this line existed.
 *
 * UUIDs are evidence, not reading: they shorten unless the page can name
 * what they point at — and *kind* says which kind of thing this one is, so
 * the page can only answer with a name of that kind.
 */
export function formatAuditValue(
  value: unknown,
  resolveId?: IdResolver,
  t?: TranslateFn,
  kind?: string,
): string {
  if (Array.isArray(value)) {
    return (
      value
        .map((item) => formatAuditValue(item, resolveId, t, kind))
        .join(", ") || "—"
    );
  }
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") {
    // A boolean is an answer, not a code: "Analytics enabled: true → false"
    // is English grammar wearing a Polish label. The catalogue carries the
    // pair the way it carries enum codes, and a catalogue that is not loaded
    // yet leaves the raw literal — the reader loses nothing they had.
    const word = t?.(`common:settings.audit.values.${value ? "YES" : "NO"}`, {
      defaultValue: "",
    });
    if (word) return word;
    return String(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return String(value);
    // `toPrecision` rather than a fixed number of decimals: it keeps a small
    // value (0.0001234) that rounding to three places would flatten to zero.
    return Number.isInteger(value)
      ? String(value)
      : String(Number(value.toPrecision(6)));
  }
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  if (UUID_PATTERN.test(text)) {
    return resolveId?.(text, kind) ?? text.slice(0, 8);
  }
  if (ISO_DATE_TIME_PATTERN.test(text) && !Number.isNaN(Date.parse(text))) {
    // A day is not a moment: `expiry_date` carries `2026-01-01`, and
    // formatting it as a timestamp printed a midnight nobody recorded.
    return text.includes("T") ? formatDateTime(text) : formatDate(text);
  }
  if (DECIMAL_STRING_PATTERN.test(text)) {
    // The reader's number, the same one the quantity fields show: the
    // store's scale ("2.000") is not a shape anybody typed.
    return formatQuantityLocale(text);
  }
  if (ENUM_CODE_PATTERN.test(text)) {
    // The catalogue lives in `common`, and this function is reached from
    // screens whose `t` is bound to another namespace (the item card reads
    // its history with the `items` translator): without the explicit
    // namespace a boolean or a code never found its word there.
    const word = t?.(`common:settings.audit.values.${text}`, {
      defaultValue: "",
    });
    if (word) return word;
  }
  return text;
}

/**
 * The writer's word for a secret that moved, whose value the journal does
 * not carry. Two identical masks on either side of an arrow read as nothing
 * happening, and the line was dropped — so a rotated API key showed up as a
 * dash in the Details column. The backend sends this instead of a second
 * mask; the reader gets it in their own language.
 */
const ROTATED_VALUE = "ROTATED_VALUE";

/**
 * The value dictionaries the reader shares with the screens that own them.
 *
 * One event, one vocabulary: the asset screen's history read
 * `Dostępny → Wycofany` while the journal read `AVAILABLE → RETIRED` for
 * the same change — two screens, two dictionaries, one status. The keys
 * here are the owning screen's own (`equipment:status.*`, the roles screen's
 * `settings.organization.memberRoles.*`), so a word changed there changes
 * here, and a code no dictionary carries stays as the record wrote it.
 */
const VALUE_RESOLVERS: Record<
  string,
  (t: TranslateFn, code: string) => string
> = {
  profile_id: (t, code) => auditProfileName(t, code, ""),
  focus_module: (t, code) => auditModuleName(t, code, ""),
  equipment_status: (t, code) =>
    t(`equipment:status.${code.toLowerCase()}`, { defaultValue: "" }),
  // The condition an asset came back in: the words the return dialog offers.
  condition: (t, code) =>
    t(`equipment:assignments.condition_${code.toLowerCase()}`, {
      defaultValue: "",
    }),
  role: (t, code) =>
    t(`common:settings.organization.memberRoles.${code}`, {
      defaultValue: "",
    }),
  // A restore writes the reason the product was deleted for as a field of its
  // own; the archive and the delete entry word the same code from `reasons`.
  deletion_reason: (t, code) =>
    t(`common:settings.audit.reasons.${code}`, { defaultValue: "" }),
};

/**
 * The fields that hold module names, one or many. A profile switch writes the
 * set it enabled and the set it disabled; onboarding writes the whole set the
 * organization starts with. Raw, that is `announcements, categories, core` —
 * the keys of the code, in a journal read by the people who run the business.
 */
const MODULE_LIST_FIELDS: ReadonlySet<string> = new Set([
  "enabled_modules",
  "enabled",
  "disabled",
]);

/**
 * A module's name as the App Store prints it, or *fallback* when the
 * catalogue has none (a community module the build does not know). The
 * built-in modules the store does not list (the base, locations, categories,
 * announcements) read from the journal's own short dictionary: onboarding
 * writes all of them into the set the organization starts with.
 */
export function auditModuleName(
  t: TranslateFn,
  name: string,
  fallback: string = name,
): string {
  return (
    t(`modules:modules.${name}.name`, { defaultValue: "" }) ||
    t(`common:settings.audit.builtInModules.${name}`, { defaultValue: "" }) ||
    fallback
  );
}

/** A workspace mode's name as the Settings screen prints it. */
export function auditProfileName(
  t: TranslateFn,
  id: string,
  fallback: string = id,
): string {
  return t(`common:profiles.${id}.name`, { defaultValue: "" }) || fallback;
}

/**
 * How a leaf value reads on a journal line — formatAuditValue, except for
 * the writer's sentinels and the dictionaries the owning screens carry. The
 * equipment status machine's UNKNOWN reads as the absence it names: the
 * writers stopped recording it, and rows that already carry it still have to
 * read as what they mean, an asset that simply had no status before, not a
 * state nobody declared. A replaced secret reads as the fact that it was
 * replaced. A value that is not there reads as the dash every other column
 * prints: `Description: abc →` was an arrow at nothing.
 */
function leafText(
  path: string,
  value: unknown,
  resolveId?: IdResolver,
  t?: TranslateFn,
): string {
  const leaf = path.split(".").pop() ?? "";
  if (t && Array.isArray(value) && MODULE_LIST_FIELDS.has(leaf)) {
    return (
      value.map((module) => auditModuleName(t, String(module))).join(", ") ||
      "—"
    );
  }
  if (t && Array.isArray(value) && leaf === "permissions") {
    // A key's permissions read by the labels its dialog shows: the page
    // names the ones the permission catalogue knows (`resolveId` with the
    // kind "permission"), this module's own wording comes next. A permission
    // no screen has a sentence for stays as the key was issued with it.
    return (
      value
        .map(
          (permission) =>
            resolveId?.(String(permission), "permission") ||
            t(
              `api_keys:capabilities.permissions.${String(permission).replace(/:/g, "_")}`,
              { defaultValue: "" },
            ) ||
            String(permission),
        )
        .join(", ") || "—"
    );
  }
  const text = formatAuditValue(value, resolveId, t, referenceKindOf(path));
  if (text === "UNKNOWN" && leaf === "equipment_status") {
    return "—";
  }
  if (text === ROTATED_VALUE) {
    return t ? t("common:settings.audit.secretChanged") : "—";
  }
  if (text === "") {
    return "—";
  }
  if (t && typeof value === "string" && path.startsWith("meta_data.")) {
    // A select field of the product form stores the option as written
    // ("Yes"), and a field the platform seeds carries a catalogue entry for
    // each option so the form can say it in the reader's language. The
    // history reads the same entry; an option nobody catalogued (a field the
    // organization made) is the owner's own word and stays as written.
    const word = t(`items:fieldOptions.${leaf}.${value}`, { defaultValue: "" });
    if (word) return word;
  }
  if (t) {
    const resolver = VALUE_RESOLVERS[leaf];
    const code = typeof value === "string" ? value : text;
    const word = resolver?.(t, code) ?? "";
    if (word) return word;
  }
  return text;
}

function walk(
  before: unknown,
  after: unknown,
  prefix: string,
  depth: number,
  out: AuditChange[],
  resolveId?: IdResolver,
  beforeName?: string | null,
  afterName?: string | null,
  t?: TranslateFn,
): void {
  // An absent side reads as an empty record so a pair can still be walked. A
  // nested setting written for the first time arrives as `null → {api_key}`,
  // and needing *both* sides to be objects meant the whole value was printed
  // as JSON — `Jina: — → {"api_key":"**********"}` — where the field names
  // were the answer. The same holds in reverse, when a value is cleared.
  const beforeFields = absentAsEmpty(before);
  const afterFields = absentAsEmpty(after);
  if (depth < MAX_DEPTH && beforeFields && afterFields) {
    for (const key of new Set([
      ...Object.keys(beforeFields),
      ...Object.keys(afterFields),
    ])) {
      // The name belongs to the id on the same line, so it is read, not
      // printed under it as a change of its own.
      if (
        isReferenceLabel(key, beforeFields) ||
        isReferenceLabel(key, afterFields)
      )
        continue;
      // `before`/`after` are the envelope's own names, never a field of the
      // record. They are read at the top level (that is what makes a change
      // an arrow rather than a list); meeting one down here means a nested
      // snapshot wrapped its own two sides, and printing it would hand the
      // reader the journal's structure instead of the record's — 5246 rows
      // apiece on the day this was measured.
      if (key === "before" || key === "after") continue;
      walk(
        beforeFields[key],
        afterFields[key],
        prefix ? `${prefix}.${key}` : key,
        depth + 1,
        out,
        resolveId,
        referenceNameOf(beforeFields, key, t),
        referenceNameOf(afterFields, key, t),
        t,
      );
    }
    return;
  }
  const was = beforeName ?? leafText(prefix, before, resolveId, t);
  const is = afterName ?? leafText(prefix, after, resolveId, t);
  // A line saying `name: X → X` is not a change, and an entry made of nothing
  // else buries the one field that did move. Entries written before the
  // snapshot was narrowed to the actual difference still carry those, so the
  // reading side drops them too. Neither is a line reading `Description: — →`:
  // an empty value turning into an empty value is nothing happening, and on a
  // location move it was the line that pushed the parent off the row.
  if (was === is || (isEmptyValue(was) && isEmptyValue(is))) return;
  out.push({ path: prefix, from: was, to: is });
}

/**
 * What an entry records, one line per leaf that moved.
 *
 * A dictionary-valued field used to be printed whole on both sides of the
 * arrow: a product's nutrition document from a food database, twice, in one
 * table cell. Only the paths that differ are named now, so the size of the
 * document stops deciding the size of the row.
 *
 * *t* is the reader's translator, when there is one: a reference the app
 * reads by code is printed in the word that code resolves to, the same word
 * every other screen uses.
 */
export function auditChanges(
  snapshot: unknown,
  _action: string,
  resolveId?: IdResolver,
  t?: TranslateFn,
): AuditChange[] {
  if (!isPlainObject(snapshot)) return [];
  const before = snapshot.before;
  const after = snapshot.after;
  if (isPlainObject(before) && isPlainObject(after)) {
    const out: AuditChange[] = [];
    walk(before, after, "", 0, out, resolveId, undefined, undefined, t);
    // The fields beside the two sides say which part of the record moved —
    // which ingredient line of a recipe, which cost line. Without them a
    // reader gets "Qty per batch: 2 → 5" about a recipe with nine
    // ingredients. They are facts, not differences, so they read like a
    // create's fields do, and they come after what changed.
    // A field the diff already speaks is not context as well: an update that
    // moves a webhook's address carries `url` flat beside the sides, and the
    // address then read twice in one cell under one key.
    const moved = new Set(out.map((change) => change.path));
    return [
      ...out,
      ...flatFields(snapshot, resolveId, t).filter(
        (change) => !moved.has(change.path),
      ),
    ];
  }
  // A flat snapshot is not only a CREATE's shape. A stock take closed says
  // what the count produced (counted, adjusted, how many differences were
  // accepted beyond the tolerance); a document confirmed names its new
  // status; an approval stage names why it skipped itself. All of that is
  // the record of what happened, and an UPDATE row showing it used to print
  // "—" instead. Same reading as a CREATE: what the entry came with, minus
  // the identity (the Target column already shows it) and minus the empties.
  return flatFields(snapshot, resolveId, t);
}

/**
 * A scan session's status, in the reader's word.
 *
 * The session journal writes the status as the session machine spells it —
 * `active`, `cancelled` — lowercase, so it is not one of the capitalised codes
 * the catalogue lookup in `formatAuditValue` recognises. The words live in
 * the same catalogue under `wms_session_<status>`; a status nobody listed
 * stays as it was written.
 */
function sessionStatusWord(
  key: string,
  value: unknown,
  t?: TranslateFn,
): string | null {
  if (key !== "wms_session_status" || typeof value !== "string") return null;
  return (
    t?.(`common:settings.audit.values.wms_session_${value}`, {
      defaultValue: "",
    }) || null
  );
}

/**
 * The snapshot's own fields, minus its identity and minus the two sides.
 *
 * What an entry came with, read the same way whether it is all an entry has
 * (a create) or context beside a change (which ingredient line moved). A
 * name hung beside a reference id is not one of those fields: it is how that
 * id reads, and it goes on the id's own line.
 */
function flatFields(
  snapshot: Record<string, unknown>,
  resolveId?: IdResolver,
  t?: TranslateFn,
): AuditChange[] {
  const identityKeys: readonly string[] = IDENTITY_KEYS;
  return Object.entries(snapshot)
    .filter(
      ([key, value]) =>
        !identityKeys.includes(key) &&
        key !== "before" &&
        key !== "after" &&
        // What an approval stands in front of is the entry's target, named
        // in the Target column by its number; printed here it was JSON.
        key !== APPROVAL_TARGET_KEY &&
        !isReferenceLabel(key, snapshot) &&
        value !== null &&
        value !== undefined &&
        value !== "" &&
        !(typeof value === "number" && value === 0),
    )
    .map(([key, value]) => ({
      path: key,
      from: null,
      to:
        referenceNameOf(snapshot, key, t) ??
        (key === FIELDS_KEY && Array.isArray(value) && t
          ? value
              .map((field) => auditFieldLabel(String(field), t))
              .join(", ") || "—"
          : (sessionStatusWord(key, value, t) ??
            leafText(key, value, resolveId, t))),
    }));
}

/**
 * A field's name as a person would say it.
 *
 * Three answers, asked in this order:
 *
 * 1. The module's own schema, when the entry belongs to a module's settings:
 *    the settings screen names each field by its ``title_key``, and a journal
 *    row reading "Allow admin self approve" said something the reader could
 *    not find anywhere in the interface. The key is resolved here, at reading
 *    time, so the entry itself stays in one language and reads back in
 *    whichever one the reader uses.
 * 2. The catalogue (`settings.audit.fields.<segment>`), when it has the word.
 * 3. The segment as the record wrote it — `min_quantity` — and not tidied into
 *    "Min quantity". The tidying is what this function used to do, and it is
 *    why forty fields went out in English without anyone noticing:
 *    `storage_location_id` became "Storage location", a shape no reader can
 *    tell from a translated label, in a journal whose reader is Polish. A raw
 *    key says the one true thing — nobody has named this field in your
 *    language yet — and the gate beside this file
 *    (`scripts/check-audit-fields.mjs`) fails when the backend declares a key
 *    no catalogue knows, so the state is loud rather than plausible. The gate
 *    sees declared keys only, which is exactly why the last answer must not
 *    pretend: a field arriving as data has no declaration to be caught by.
 *
 * A nested path keeps its parents so `meta_data.nutrition.fat` still says
 * which document it came out of.
 */
/**
 * Fields the journal names with the word the product form uses, not a word of
 * its own: the journal said "Shelf / position" for what the form, the product
 * page and the export call "Shelf Location".
 */
const NAMED_BY_THE_FORM: Record<string, string> = {
  shelf_location: "items:itemShelfLocation",
};

export function auditFieldLabel(
  path: string,
  t: TranslateFn,
  titles?: Record<string, string>,
): string {
  const titleKey = titles?.[path];
  if (titleKey) {
    const title = t(titleKey, { defaultValue: "" });
    if (title) return title;
  }
  return path
    .split(".")
    .map(
      (segment) =>
        (NAMED_BY_THE_FORM[segment] &&
          t(NAMED_BY_THE_FORM[segment], { defaultValue: "" })) ||
        t(`settings.audit.fields.${segment}`, { defaultValue: "" }) ||
        segment,
    )
    .join(" › ");
}
