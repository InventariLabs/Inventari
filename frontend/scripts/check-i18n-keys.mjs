#!/usr/bin/env node
/**
 * check-i18n-keys.mjs
 *
 * Static guard that cross-checks translation keys USED in code against the
 * keys DEFINED in the locale catalogs — the gap that neither
 * `coreLocaleParity.test.ts` (catalog ↔ catalog) nor `lint-i18n-raw.mjs`
 * (raw strings in toasts) covers. Catches the bug class where a key is
 * missing from ALL locales at once and every language renders the raw key
 * or a hardcoded fallback.
 *
 * What it does:
 *   1. Scans src/**​/*.{ts,tsx} (tests excluded) for t() calls and resolves
 *      their namespaces:
 *        - useTranslation("ns") / useTranslation(["ns1", "ns2"])
 *        - aliased hooks: const { t: tScan } = useTranslation("scan")
 *        - explicit prefix: t("items:itemNotFound")
 *        - options override: t("key", { ns: "scan" })
 *        - no argument → defaultNS "common" (see src/i18n/config.ts)
 *   2. Loads catalogs from src/i18n/locales/<lang>/<ns>.json and
 *      src/modules/<mod>/i18n/<lang>.json (namespace = module dir name,
 *      mirroring the glob registration in config.ts).
 *   3. A key is satisfied when the catalog has the leaf or any plural
 *      variant (key_one/_few/_many/_other). For t(key, { count }) it
 *      additionally fails when Polish has only `_other` — the
 *      "1 pozycje" bug class (missing _one/_few paucal forms).
 *   4. It then sweeps every catalog for `{{count}}` values missing their CLDR
 *      variants, in all five languages, plus hand-rolled shorthands like
 *      "1 line(s)" / "1 Dokument(e)". This is the only mechanism for that
 *      class: `countPluralContract.test.ts` used to own it, blocking but
 *      reading three module catalogs it imported by hand, while this file saw
 *      every namespace and printed warnings nothing acted on. A wide rule
 *      without teeth beside a narrow one with them is how
 *      `launcher.actionItems.subtitle` shipped with a bare `{{count}}`.
 *   5. Dynamic keys (template literals) are reported separately and never
 *      fail the check.
 *   6. Compares every plural family's form hashes against
 *      scripts/i18n-plural-snapshot.json and fails when SOME forms of a
 *      family changed while their sisters kept the old wording — presence of
 *      all forms says nothing about whether they still say the same thing.
 *      The snapshot refreshes only through --write-plural-snapshot.
 *   7. Compares each Polish value against its English source and fails when
 *      the Polish names a unit noun ("sztuk", "szt.") the English does not
 *      ("piece/unit/pcs/each"). A translated catalogue can invent a unit the
 *      source never had — "Ile sztuk ... (dostępne 7.900 kg)" — and every
 *      other check stays green by design, because the key exists, is used and
 *      is not a raw string.
 *   8. Fails when a screen's own name (`*.title` / `*.subtitle` / `*.heading`)
 *      is byte-identical to English in pl.json while de, fr AND es all
 *      translated it — the one shape a title left in English takes. Scoped to
 *      names because Polish borrows field labels wholesale (Model, VAT, Email)
 *      and a rule over every key would fire seventeen times to catch one.
 *
 * Modes:
 *   node check-i18n-keys.mjs                 # full report, exit 1 on violations
 *   node check-i18n-keys.mjs --baseline      # only NEW violations vs baseline fail
 *   node check-i18n-keys.mjs --unused        # full report, exit 1 on orphan keys
 *   node check-i18n-keys.mjs --unused --baseline  # only NEW orphans fail
 *   node check-i18n-keys.mjs --write-baseline# snapshot current state as baseline (keys only)
 *   node check-i18n-keys.mjs --write-plural-snapshot # refresh the plural-form content snapshot
 *   node check-i18n-keys.mjs --plural-report # how many pl families carry two vocabularies (informational)
 *   node check-i18n-keys.mjs --quiet         # summary only
 *   node check-i18n-keys.mjs --sync-backend  # refresh the backend-key snapshot
 *
 * The --unused mode is the reverse direction: keys DEFINED in the catalogs
 * but never resolved by the static scanner (orphans after code removal).
 * Reports exact leaf keys; genuine plural families (>=2 forms) are matched
 * against the base key used in t() calls. Dynamically consumed keys are
 * exempt via DYNAMIC_ALLOWLIST above.
 *
 * Baseline file: frontend/scripts/i18n-keys-baseline.json
 * The goal is an EMPTY baseline — fix findings, don't grandfather them.
 *
 * Backend-declared keys: backend module manifests declare frontend i18n keys
 * for settings forms and the RBAC matrix (`title_key`, `description_key`,
 * `label_key`). They have no frontend call site, so they are mirrored into
 * frontend/scripts/i18n-backend-keys.json — see loadBackendKeys() below.
 */
import {
  readFileSync,
  readdirSync,
  statSync,
  writeFileSync,
  existsSync,
} from "node:fs";
import { createHash } from "node:crypto";
import { resolve, relative, join, basename } from "node:path";

import { shorthandPermissionKeys } from "./manifest-permission-keys.mjs";

const ROOT = resolve(new URL("..", import.meta.url).pathname); // frontend/
const SRC = resolve(ROOT, "src");
/**
 * A second tree shaped like `src/` — source files anywhere in it, module
 * catalogs under `modules/<mod>/i18n/` — scanned beside the real one. It
 * exists for the gate's own tests. They used to write their fixtures into
 * `src/`, where every other scanner in the same vitest pass could list a
 * fixture a moment before this test deleted it and then fail to read it.
 */
const EXTRA_SRC = process.env.I18N_EXTRA_SRC
  ? resolve(process.env.I18N_EXTRA_SRC)
  : null;
const SOURCE_ROOTS = EXTRA_SRC ? [SRC, EXTRA_SRC] : [SRC];
/** The env overrides let the test point the gate at files of its own. */
const BASELINE_PATH = resolve(
  ROOT,
  process.env.I18N_KEYS_BASELINE ?? "scripts/i18n-keys-baseline.json",
);
/**
 * Content reference for plural families, machine-managed like
 * i18n-backend-keys.json. The env override exists so the test can point the
 * gate at a snapshot of its own making instead of the tree's.
 */
const PLURAL_SNAPSHOT_PATH = resolve(
  ROOT,
  process.env.I18N_PLURAL_SNAPSHOT ?? "scripts/i18n-plural-snapshot.json",
);
const LANGUAGES = ["en", "pl", "de", "fr", "es"];
const DEFAULT_NS = "common";
const PLURAL_SUFFIXES = ["_zero", "_one", "_two", "_few", "_many", "_other"];
const SKIP_PATH_PARTS = [
  "__tests__",
  "__mocks__",
  "/test/",
  "/tests/",
  ".test.",
  ".spec.",
  "/i18n/",
];

// ---------------------------------------------------------------------------
// Dynamic consumption allowlist (used by the --unused mode)
// ---------------------------------------------------------------------------

/**
 * Keys that the static t() scanner can never resolve because they are
 * consumed via makeTDynamic / template literals or the module registry:
 *   - common:statuses.* — tDyn(`statuses.${status}`) (src/lib/i18nHelpers.ts)
 *   - common:profiles.* — tDyn(`common:profiles.${profileId}.subtitle`) etc.
 *   - <any>:navigation.* — nav labels consumed via tDyn(item.labelKey) in
 *     AppShell / module.ts registrations (labelKey: "mod:navigation.x")
 *   - <mod>:displayName — ModuleTile: tDyn(cfg.displayName)
 *   - <mod>:description — ModuleTile / settings: tDyn(cfg.description)
 * `ns: "*"` matches every namespace. By default a prefix matches the exact
 * key or a dot-descendant (`prefix` / `prefix.x`); `raw: true` switches to a
 * plain string prefix match for underscore/camelCase concatenations
 * (e.g. `workflows.targetType_document`, `filterActive`).
 */
const DYNAMIC_ALLOWLIST = [
  { ns: "common", prefix: "statuses" },
  // StockMovesPage: the direction tabs are built from a list of the four
  // readings, and the source badge reads t(`...source.${reference_type}`) —
  // one key per kind of thing a movement can come from.
  { ns: "inventory", prefix: "moves.direction" },
  { ns: "inventory", prefix: "moves.source" },
  // StockLotPage: t(`...lot.status.${lot.status}`) — one label per state a
  // batch can be in (LotStatus in the core contracts).
  { ns: "inventory", prefix: "lot.status" },
  // StockLotsPage: t(`...lots.setTo.${status}`) — one menu entry per state a
  // batch can be moved into.
  { ns: "inventory", prefix: "lots.setTo" },
  // DocumentExtraCostsSection: t(`...extraCosts.kind.${kind}`) and
  // t(`...extraCosts.method.${method}`) — one label per kind of delivery
  // cost and per way of splitting it.
  // ImportModal (products): t(`...labelMatch.modes.${mode}`) and
  // t(`...labelMatch.notes.${mode}`) — one chip and one sentence per thing a
  // row can do when its label code names a product already here.
  { ns: "items", prefix: "import.labelMatch.modes" },
  { ns: "items", prefix: "import.labelMatch.notes" },
  // DocumentHistoryPage: t(`...history.chips.${chip}`) — one tab per kind of
  // action — and describeHistoryEntry: t(`...history.sentence.${type}`) — one
  // sentence per document type, with a "Partner" form for receipts and issues.
  { ns: "warehouse", prefix: "history.chips" },
  { ns: "warehouse", prefix: "history.sentence" },
  { ns: "warehouse", prefix: "extraCosts.kind" },
  { ns: "warehouse", prefix: "extraCosts.method" },
  // PlannedPutawayLine: t(`...ruleMatchKeys.${key}`) — one word per key a
  // putaway rule can match by; and t(`...plannedRuleWarning.${warning}`) —
  // one sentence per reason a matched rule had to step aside.
  { ns: "warehouse", prefix: "detail.ruleMatchKeys" },
  { ns: "warehouse", prefix: "detail.plannedRuleWarning" },
  // auditChanges.formatAuditValue: a code the backend wrote into a snapshot
  // is looked up as t(`settings.audit.values.${text}`) — one word per
  // enumerated value the journal can print (`ALL`, `STORAGE`, `CATEGORY`).
  // The set is open on purpose: a code the catalogue does not know stays as
  // it arrived, which is where every one of them was before the lookup.
  { ns: "common", prefix: "settings.audit.values" },
  // auditChanges.auditModuleName: a module key in an enabled-modules list is
  // looked up as t(`settings.audit.builtInModules.${key}`) after the App Store
  // catalogue has no name for it — the four built-in modules the store does
  // not list. A key the dictionary does not know (a community module) stays
  // as it arrived.
  { ns: "common", prefix: "settings.audit.builtInModules" },
  // LabelSettingsSidebar: the preset table carries the catalogue key as data
  // (`{ word: "previewModal.preset.narrow", width, height }`), because the
  // name a reader sees is one word plus two numbers that read the same in
  // every language — and the numbers cannot live in a translated string
  // without seven sentences per language saying the same thing five ways.
  { ns: "labels", prefix: "previewModal.preset" },
  // OrganizationMembers: t(`...memberRoleAccess.${access}`) — one summary per
  // access level a built-in role maps to (memberRoleAccess.ts).
  { ns: "common", prefix: "settings.organization.memberRoleAccess" },
  { ns: "common", prefix: "profiles" },
  // AppStore: t(CATEGORY_LABEL_KEY[category]) — one key per store taxonomy
  // bucket, rendered only when a module is in it.
  { ns: "common", prefix: "appStore.category", raw: true },
  // AppStore: t(OFF_HAS_CONSEQUENCES[moduleName]) — the sentence saying what
  // switching a module off revokes, for the modules whose "off" reaches
  // outside the workspace. One key per such module, looked up by name. Its own
  // prefix rather than sitting under `appStore.deactivate`, which would have
  // exempted the button label and the dialog title from this check too.
  { ns: "common", prefix: "appStore.offConsequences", raw: true },
  { ns: "*", prefix: "navigation" },
  { ns: "*", prefix: "displayName" },
  { ns: "*", prefix: "description" },
  // FieldRenderers/helpers: getLabel resolves a system field's label by the
  // field's key — t(`items:fields.${field.key}`) — one label per field a
  // module declaration or profile seed declares. The keys arrive as data on
  // the category and never appear as literals in this tree, so each one is
  // named here explicitly: a key added to the catalog without a consumer
  // must still surface as an orphan, which a bare "fields" prefix would
  // have hidden.
  // FieldRenderers/SelectField: a `select` option's word is resolved through
  // `tDyn`, not `t`, so this scanner cannot see any of these call sites — the
  // two fixed ones included. `fieldOptions.none` is the empty choice and
  // `fieldOptions.unknownValue` marks a stored value the option list does not
  // contain; both are literals in SelectField.tsx. The per-option entries are
  // reached as data: a declaration names a key per option (`options_i18n`),
  // and a seeded field's options are catalogued here the way its label is.
  // Listed one by one rather than under a "fieldOptions" prefix, so a key
  // added to the catalog with nothing consuming it still surfaces as an
  // orphan.
  { ns: "items", prefix: "fieldOptions.none" },
  { ns: "items", prefix: "fieldOptions.unknownValue" },
  { ns: "items", prefix: "fieldOptions.lactose_free.No" },
  { ns: "items", prefix: "fieldOptions.lactose_free.Yes" },
  { ns: "items", prefix: "fields.asset_tag" },
  { ns: "items", prefix: "fields.manufacturer" },
  { ns: "items", prefix: "fields.model" },
  { ns: "items", prefix: "fields.ram_gb" },
  { ns: "items", prefix: "fields.storage_gb" },
  { ns: "items", prefix: "fields.os" },
  { ns: "items", prefix: "fields.group_tag" },
  { ns: "items", prefix: "fields.purchase_date" },
  { ns: "items", prefix: "fields.warranty_until" },
  { ns: "items", prefix: "fields.equipment_status" },
  { ns: "items", prefix: "fields.useful_life_years" },
  { ns: "items", prefix: "fields.size_inches" },
  { ns: "items", prefix: "fields.resolution" },
  { ns: "items", prefix: "fields.imei" },
  { ns: "items", prefix: "fields.phone_number" },
  { ns: "items", prefix: "fields.ip_address" },
  { ns: "items", prefix: "fields.mac_address" },
  { ns: "items", prefix: "fields.rack_position" },
  { ns: "items", prefix: "fields.cpu" },
  { ns: "items", prefix: "fields.cut_type" },
  { ns: "items", prefix: "fields.freeze_date" },
  { ns: "items", prefix: "fields.lactose_free" },
  { ns: "items", prefix: "fields.abv" },
  // Verified dynamic-consumption families (template literals / t(var) maps):
  { ns: "api_keys", prefix: "table" }, // ApiKeysPage: t(`table.${col}`)
  // ApiKeyCapabilitiesCard: t(`capabilities.permissions.${key}`) — one label
  // per permission /api-keys/capabilities can report.
  { ns: "api_keys", prefix: "capabilities.permissions" },
  // RolePermissionsSheet: t(permission.label_key) — the roles editor renders
  // whatever GET /roles/permission-catalog declares, so the key arrives as
  // data. One label and one description per SystemPermission.
  { ns: "permissions", prefix: "system" },
  // WebhookForm: t(`events.${ev.event_type}`) — one key per event the
  // backend catalogue can return.
  { ns: "webhooks", prefix: "events" },
  { ns: "approvals", prefix: "dashboard.docTypes" }, // ApprovalsDashboard
  { ns: "approvals", prefix: "dashboard.tabs" }, // t(tab.key)
  { ns: "approvals", prefix: "dashboard.targetTypes" }, // t(TARGET_TYPE_LABELS[x])
  { ns: "approvals", prefix: "workflows.targetType_", raw: true },
  // AnnouncementBanner: t(`types.${a.type}`) — one label per announcement
  // type the backend accepts.
  { ns: "announcements", prefix: "types" },
  // roleLabels.ts: t(`workflows.roles.${role}`) for known RBAC roles.
  { ns: "approvals", prefix: "workflows.roles" },
  // PasswordRules / ResetPasswordPage: t(`passwordPolicy.rules.${rule}`) and
  // t(`passwordPolicy.errors.${rule}`) — one line per rule the account
  // password policy states (passwordPolicy.ts).
  { ns: "auth", prefix: "passwordPolicy.rules" },
  { ns: "auth", prefix: "passwordPolicy.errors" },
  // CategoryFormModal: t(`modal.namePlaceholderProfiles.${profile}`) — one
  // example per product profile, picked from the organization's own.
  { ns: "categories", prefix: "modal.namePlaceholderProfiles" },
  // ColorSwatchPicker: t(`modal.colors.${key}`) — one name per palette key
  // the picker can render (PALETTE_KEYS). The gate that keeps this complete
  // is the component's own test, which walks the palette against all five
  // catalogues; this entry only says the consumption is dynamic.
  { ns: "categories", prefix: "modal.colors" },
  // LoginPage: t(loginFailureKey(error)) — one sentence per cause a failed
  // sign-in can have (loginFailure.ts).
  { ns: "auth", prefix: "login.networkError", raw: true },
  { ns: "auth", prefix: "login.tooManyAttempts", raw: true },
  { ns: "auth", prefix: "login.serverError", raw: true },
  { ns: "auth", prefix: "login.failed", raw: true },
  { ns: "auth", prefix: "invalidCredentials", raw: true },
  // useScanResolver: t(ELSEWHERE_KEY[subject.kind]) — one sentence per kind
  // of thing the scan registry can recognize, shown when the code is valid
  // but this screen is not where it belongs.
  { ns: "scan", prefix: "elsewhere" },
  // LabelScanPage: tDynamic(data.message_key, data.message_params) — the line
  // under the scan's status arrives from the server as a key, because the
  // server cannot know which language the phone's reader holds. One key per
  // answer the scan chain can give (app/core/scan_providers.py and the two
  // module providers). The keys never appear as literals in this tree, so the
  // entry is the prefix and nothing more.
  { ns: "scan", prefix: "result" },
  // LabelSettingsSidebar: t(`previewModal.mediaOption.${key}`) and the hint
  // beside it — one name and one sentence per media profile a label can be
  // rendered for (GET /labels/media).
  { ns: "labels", prefix: "previewModal.mediaOption" },
  { ns: "labels", prefix: "previewModal.mediaHint" },
  { ns: "categories", prefix: "codes" }, // CategoriesPage / CategoryField
  { ns: "categories", prefix: "groups" }, // CategoriesPage: t(`groups.${group}`)
  // AiConnectionFields / ProviderTileGrid: t(providerDescriptionKey(id)) —
  // one line per provider the picker offers.
  { ns: "modules", prefix: "config.providerDescription" },
  // WidgetsPage: t(`colors.${color}`) — one name per colour the module's
  // schema accepts.
  { ns: "example_widgets", prefix: "colors" },
  // ReasonCodeField: the caller passes `labelFor`, which is
  // t(`reasons.<list>.codes.${code}`) — one label per reason a correction, a
  // return, a write-off or a counted difference can carry (the backend enums
  // own the lists).
  { ns: "warehouse", prefix: "reasons.correction" },
  { ns: "warehouse", prefix: "reasons.return" },
  { ns: "warehouse", prefix: "reasons.scrap" },
  { ns: "stock_takes", prefix: "reasons.discrepancy" },
  { ns: "warehouse", prefix: "profile.presets" }, // ProfilePresetSelector: t(`...${slug}`)
  { ns: "stats", prefix: "analytics.forecast.trends" }, // ExpenseForecastChart: t(`...${data.trend}`)
  { ns: "common", prefix: "units" }, // DefaultInputField: t(`common:units.${u}`)
  { ns: "common", prefix: "datePresets" }, // DateInput: t(`datePresets.${preset}`)
  { ns: "common", prefix: "settings.organization.memberRoles" }, // OrganizationSettings: t(`...${role}`)
  { ns: "common", prefix: "settings.audit.actions" }, // AuditLogPage (ns=common)
  { ns: "common", prefix: "settings.audit.reasons" },
  // AuditLogPage names a changed field through its path segment.
  { ns: "common", prefix: "settings.audit.fields" },
  { ns: "common", prefix: "settings.audit.targetTypes" },
  { ns: "common", prefix: "settings.theme_", raw: true }, // ThemeToggle
  { ns: "warehouse", prefix: "actions" }, // DocumentsPage: t(`actions.${a}`)
  // Two pages build this family out of an action name:
  // DocumentsPage t(`confirmDialog.${type}Title|Message`) and
  // DocumentDetailPage t(`confirmDialog.${confirmAction}Title`) — so the
  // eight reachable keys are named here one by one. The family used to be
  // exempt as a whole, which made every future key under `confirmDialog`
  // invisible to this gate; naming the reachable set turns the rest back
  // into findings.
  { ns: "warehouse", prefix: "confirmDialog.confirmTitle" },
  { ns: "warehouse", prefix: "confirmDialog.confirmMessage" },
  { ns: "warehouse", prefix: "confirmDialog.completeTitle" },
  { ns: "warehouse", prefix: "confirmDialog.completeMessage" },
  { ns: "warehouse", prefix: "confirmDialog.cancelTitle" },
  { ns: "warehouse", prefix: "confirmDialog.cancelMessage" },
  { ns: "warehouse", prefix: "confirmDialog.deleteTitle" },
  { ns: "warehouse", prefix: "confirmDialog.deleteMessage" },
  { ns: "warehouse", prefix: "detail.discrepancyCodes" },
  { ns: "warehouse", prefix: "detail.lineStatuses" },
  { ns: "warehouse", prefix: "errors" }, // t(errors.x) / t(msg) / t(firstKey)
  { ns: "warehouse", prefix: "picker" }, // DocumentFormHeader
  { ns: "warehouse", prefix: "picking.status" },
  { ns: "warehouse", prefix: "receiving.line" }, // WmsReceiveLineRow status map
  { ns: "warehouse", prefix: "register.groupBy_", raw: true },
  { ns: "warehouse", prefix: "status" }, // DocumentStatusTimeline
  { ns: "warehouse", prefix: "templates.layouts" }, // DocumentsTemplatesPage
  { ns: "warehouse", prefix: "types" }, // DocumentDetailPage
  { ns: "warehouse", prefix: "typesShort" }, // DocumentRegisterPage: t(`typesShort.${code}`)
  { ns: "warehouse", prefix: "units" }, // unitLabels.ts
  { ns: "warehouse", prefix: "statusBadge" }, // t(badge.labelKey)
  { ns: "equipment", prefix: "approvals.status_", raw: true },
  { ns: "equipment", prefix: "assignments.condition_", raw: true },
  { ns: "equipment", prefix: "attachments.type_", raw: true },
  { ns: "equipment", prefix: "maintenance.type_", raw: true },
  { ns: "equipment", prefix: "status" }, // DynamicFieldsCard: STATUS_LABEL_KEYS map
  { ns: "equipment", prefix: "statusBadge" }, // t(badge.labelKey)
  { ns: "equipment", prefix: "timeline.type_", raw: true },
  // assetUtils.getCategoryLabel: static key map consumed by data-driven lookup
  { ns: "equipment", prefix: "categories.codes" },
  // campaignLabels.ts: same shape — status codes looked up in a static map
  { ns: "equipment", prefix: "attestation.status" },
  { ns: "equipment", prefix: "attestation.responseStatus" },
  // assetUtils.getLocationLabel: seeded location codes, same static-map shape
  { ns: "equipment", prefix: "locations.seeded" },
  // DynamicFieldsCard: t(`form.fields.${camelCase(field.key)}`, field.label)
  { ns: "equipment", prefix: "form.fields" },
  { ns: "inventory", prefix: "statusBadge" }, // t(badge.labelKey)
  { ns: "items", prefix: "history.actions" }, // ItemHistoryTimeline labelKey
  // ArchivedItemSheet / ArchivedItemsPage: t(`deletionReasons.${row}`) — the
  // value comes out of the database, and rows written before the neutral
  // vocabulary still say CONSUMED/DISCARDED.
  { ns: "items", prefix: "deletionReasons" },
  { ns: "items", prefix: "quantityHints" },
  { ns: "items", prefix: "placeholders" }, // helpers.ts: tDyn(`items:placeholders.${field.key}`)
  { ns: "items", prefix: "untitledField" }, // helpers.ts getLabel fallback (tDyn param)
  { ns: "items", prefix: "itemWeight" }, // computeFieldDefinitions: unit-dependent label
  { ns: "items", prefix: "itemVolume" }, // computeFieldDefinitions: unit-dependent label
  { ns: "items", prefix: "uomNames" },
  { ns: "items", prefix: "uomSymbols" },
  { ns: "launcher", prefix: "sections" },
  { ns: "maker", prefix: "productionList.status" },
  { ns: "maker", prefix: "detail.cost.kind" }, // CostLinesEditor: t(`detail.cost.kind.${kind}`)
  { ns: "maker", prefix: "settings.strategy", raw: true }, // MakerSettingsPanel: t(`settings.strategy${s}`)
  { ns: "modules", prefix: "modules" }, // AppStore: t(`modules.${m}.name`)
  { ns: "nutrition", prefix: "levels" }, // FoodAndHealthExtra
  { ns: "partners", prefix: "filter", raw: true }, // filterActive/Inactive/All
  { ns: "partners", prefix: "types" }, // PartnerDetailSheet: t(`types.${type}`)
  { ns: "purchase_orders", prefix: "status" }, // POActionBar/ListItem: t(`status.${po.status}`)
  { ns: "recipes", prefix: "allergens" },
  { ns: "recipes", prefix: "availability" },
  { ns: "recipes", prefix: "ingredient_defaults.nutrient_", raw: true }, // NutritionAddForm: t(`…nutrient_${field}`)
  { ns: "recipes", prefix: "meal_planner.slots" },
  { ns: "recipes", prefix: "picking.status" }, // PickingItemRow
  // PickingItemRow: t(`picking.not_taken.${refusal}`) — the standing line
  // on a row whose scan the server refused, one key per refusal status.
  { ns: "recipes", prefix: "picking.not_taken" },
  { ns: "recipes", prefix: "unit_conversions.category_", raw: true }, // ConversionAddForm
  { ns: "recipes", prefix: "unit_conversions.units" },
  { ns: "modules", prefix: "config.capability" }, // AiConnectionCard/PurposeBindingSelect (ns=modules)
  { ns: "stats", prefix: "analytics.alerts.types" },
  { ns: "stock_takes", prefix: "report" }, // StockTakeReportPage: tDyn(`report.${card.key}`)
  { ns: "stock_takes", prefix: "statuses" }, // StockTakesPage: tDyn(`statuses.${status}`)
  { ns: "locations", prefix: "fieldLabels" },
  { ns: "locations", prefix: "wizard.fields" },
  { ns: "locations", prefix: "suggestions" }, // StorageWizard: t(`suggestions.${kind}`) + profiles.<profile>.<kind>
  { ns: "locations", prefix: "usage" }, // STORAGE_USAGE_OPTIONS: t(`usage.${value}`)
  { ns: "*", prefix: "gettingStarted" }, // GettingStarted: t(`${mod}:gettingStarted.*`)
  // Module-registry labelKeys / displayName consumed via tDyn (module.ts):
  { ns: "*", prefix: "launcher" }, // displayName/description: "<mod>:launcher.*"
  { ns: "*", prefix: "nav" }, // nav item labelKey: "<mod>:nav.*"
  { ns: "*", prefix: "scanMode" }, // scanMode labelKey: "<mod>:scanMode.*"
  // FloorWorkSection: t(entry.label_key, { defaultValue: entry.name }) — one
  // label per pick order the registry can hold (GET
  // /documents/profile/pick-order-strategies). The keys arrive as data —
  // one per strategy a module registers, `<mod>:pickOrderStrategies.<name>`
  // — so no call site in this tree names any of them, and the set is open
  // on purpose: the entries are exactly what the registry returned.
  { ns: "*", prefix: "pickOrderStrategies" },
  // ApprovalBadge STATUS_LABEL_KEYS map: t(STATUS_LABEL_KEYS[status])
  { ns: "approvals", prefix: "request.pending" },
  { ns: "approvals", prefix: "request.inProgress" },
  { ns: "approvals", prefix: "request.approved" },
  { ns: "approvals", prefix: "request.rejected" },
  { ns: "approvals", prefix: "request.cancelled" },
];

// ---------------------------------------------------------------------------
// Key literals carried as data (not passed to t() at the definition site)
// ---------------------------------------------------------------------------

/**
 * Props that carry an i18n key as data for a generic renderer to translate
 * later — `label: "fields.purchase_price"` in a field definition,
 * `labelKey: "items:deletionReasons.LOST"` in a reason list. The t() scanner
 * cannot see these, so without this pass they look both unreferenced (the
 * --unused sweep deletes them) and unverifiable (a typo or a deleted key
 * renders as its own raw key in the UI).
 */
const KEY_LITERAL_PROPS = [
  "label",
  "labelKey",
  "placeholder",
  "placeholderKey",
  "titleKey",
  "title_key",
  "descriptionKey",
  "description_key",
  "nameKey",
  "tooltipKey",
  "helpKey",
  "i18nKey",
];

/**
 * Files whose key literals are translated somewhere else entirely, so the
 * scanner cannot read the namespace off a local useTranslation() call.
 * Keep this list short — it is a statement about who renders the file.
 */
const KEY_LITERAL_NAMESPACES = [
  {
    // Item-form vocabulary; rendered by UnifiedFieldRenderer, which calls
    // useTranslation(["items", "common", "categories"]).
    file: "src/config/systemFields.ts",
    namespaces: ["items", "common", "categories"],
  },
  {
    // AI provider group headers; rendered by ProviderTileGrid, which calls
    // useTranslation("modules").
    file: "src/modules/settings/components/ai/providers.ts",
    namespaces: ["modules"],
  },
];

/**
 * True when a literal is an i18n key rather than a human-readable label.
 * Field definitions mix both: custom fields carry free text ("Warranty
 * until"), system fields carry keys ("itemBrand", "fields.purchase_price").
 * Mirrors looksLikeKey() in FieldRenderers/helpers.ts — keep them in sync.
 */
function looksLikeI18nKey(value) {
  if (!/^[A-Za-z][\w.:-]*$/.test(value)) return false;
  return value.includes(".") || value.includes(":") || /[a-z][A-Z]/.test(value);
}

function isDynamicallyConsumed(ns, key) {
  return DYNAMIC_ALLOWLIST.some(({ ns: nsPat, prefix, raw }) => {
    if (nsPat !== "*" && nsPat !== ns) return false;
    if (raw) return key.startsWith(prefix);
    return key === prefix || key.startsWith(`${prefix}.`);
  });
}

// ---------------------------------------------------------------------------
// Keys declared in backend module manifests
// ---------------------------------------------------------------------------

// The two paths are overridable so the gate's own test can point them at a
// fixture tree and snapshot instead of the installation's.
const BACKEND_KEYS_PATH = resolve(
  ROOT,
  process.env.I18N_BACKEND_KEYS ?? "scripts/i18n-backend-keys.json",
);
const BACKEND_MODULES = resolve(
  ROOT,
  process.env.I18N_BACKEND_MODULES ?? "../backend/app/modules",
);
// Two shapes, because the backend declares keys in two places: a dict entry
// in a settings schema (`'title_key': 'equipment:settings.x'`) and a keyword
// argument (`register_purpose(label_key='recipes:ai.purposeLabel')`). Reading
// only the first is how four AI-purpose keys shipped without a translation in
// any of the five catalogs — the gate existed, and was looking the other way.
const BACKEND_KEY_RE =
  /['"]?\b\w*(?:_key|Key)['"]?\s*[:=]\s*['"]([A-Za-z0-9_]+:[A-Za-z0-9_.]+)['"]/g;
const BACKEND_DECL_FILES = [
  "module.py",
  "manifest.json",
  "_module_declarations.py",
];

function collectJsonKeys(node, out) {
  if (Array.isArray(node)) {
    for (const v of node) collectJsonKeys(v, out);
  } else if (node && typeof node === "object") {
    if (Array.isArray(node.permissions) && typeof node.name === "string") {
      for (const key of shorthandPermissionKeys(node.permissions, node.name)) {
        out.add(key);
      }
    }
    for (const [k, v] of Object.entries(node)) {
      if (typeof v === "string" && /(?:_key|Key)$/.test(k) && v.includes(":")) {
        out.add(v);
      } else {
        collectJsonKeys(v, out);
      }
    }
  }
}

/**
 * Category codes a module seeds, read as the i18n keys they resolve through.
 *
 * `CategoryDeclaration(code=...)` is the backend's promise that the code
 * exists; `categoryLabel` (src/lib/i18nHelpers.ts) resolves it as
 * `categories:codes.<code>`. A module's code keeps whatever spelling it
 * chose — core seeds lowercase, equipment seeds uppercase — because the
 * catalogue, not the spelling, is where a name lives: the shared `categories`
 * namespace carries every module's codes so a picker in the core shell can
 * name them. Registering each seeded code as the key the frontend will look
 * up is what makes a module that seeds a category no catalogue can translate
 * fail this gate, in all five languages.
 */
function categoryCodesIn(text) {
  const codes = [];
  const opener = /\bCategoryDeclaration\s*\(/g;
  let match;
  while ((match = opener.exec(text)) !== null) {
    let depth = 1;
    let i = opener.lastIndex;
    for (; i < text.length && depth > 0; i++) {
      const char = text[i];
      if (char === "(") depth += 1;
      else if (char === ")") depth -= 1;
    }
    const call = text.slice(opener.lastIndex, i - 1);
    const code = /\bcode\s*=\s*['"]([^'"]+)['"]/.exec(call);
    if (code) codes.push(code[1]);
  }
  return codes;
}

/** Frontend i18n keys declared in backend module manifests, or null when the
 *  backend tree is not mounted where `BACKEND_MODULES` points. */
function extractBackendKeys() {
  if (!existsSync(BACKEND_MODULES)) return null;
  const found = new Set();
  for (const entry of readdirSync(BACKEND_MODULES, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    for (const name of BACKEND_DECL_FILES) {
      const file = join(BACKEND_MODULES, entry.name, name);
      if (!existsSync(file)) continue;
      const text = readFileSync(file, "utf8");
      if (name.endsWith(".json")) {
        collectJsonKeys(JSON.parse(text), found);
      } else {
        for (const m of text.matchAll(BACKEND_KEY_RE)) found.add(m[1]);
        for (const code of categoryCodesIn(text)) {
          found.add(`categories:codes.${code}`);
        }
      }
    }
  }
  return [...found].sort();
}

/**
 * The snapshot keeps the check deterministic where the backend tree is not
 * mounted at `BACKEND_MODULES`. Where it is — the frontend container mounts
 * `backend/app` read-only, and CI runs on the host — the snapshot is verified
 * against the tree, so it can never drift unnoticed.
 */
function loadBackendKeys() {
  const snapshot = existsSync(BACKEND_KEYS_PATH)
    ? JSON.parse(readFileSync(BACKEND_KEYS_PATH, "utf8"))
    : [];
  const actual = extractBackendKeys();

  if (process.argv.includes("--sync-backend")) {
    if (actual === null) {
      console.error(
        `✗ --sync-backend needs the backend tree at ${relative(ROOT, BACKEND_MODULES)}`,
      );
      process.exit(1);
    }
    writeFileSync(BACKEND_KEYS_PATH, `${JSON.stringify(actual, null, 2)}\n`);
    console.log(`✓ backend key snapshot refreshed (${actual.length} keys)`);
    process.exit(0);
  }

  if (actual !== null) {
    const added = actual.filter((k) => !snapshot.includes(k));
    const removed = snapshot.filter((k) => !actual.includes(k));
    if (added.length > 0 || removed.length > 0) {
      for (const k of added) console.error(`BACKEND-KEY ADDED   ${k}`);
      for (const k of removed) console.error(`BACKEND-KEY REMOVED ${k}`);
      console.error(
        "✗ backend key snapshot is stale — run: npm run check:i18n:sync-backend",
      );
      process.exit(1);
    }
  }
  return snapshot;
}

// ---------------------------------------------------------------------------
// Catalog loading
// ---------------------------------------------------------------------------

/** ns -> lang -> Set of flat keys */
const catalogs = new Map();
/** ns -> Set of flat keys that are object/array NODES (not leaves) in some
 * language catalog. Nodes are structural: they cannot be deleted without
 * deleting their children, so --unused never reports them as orphans. */
const nodeKeys = new Map();

function flatKeys(node, prefix = [], out = [], nodes = [], values = []) {
  if (node == null) return out;
  if (typeof node === "string" || typeof node === "number") {
    out.push(prefix.join("."));
    values.push([prefix.join("."), String(node)]);
    return out;
  }
  if (Array.isArray(node)) {
    if (prefix.length > 0) {
      out.push(prefix.join(".")); // node key (returnObjects)
      nodes.push(prefix.join("."));
    }
    node.forEach((v, i) =>
      flatKeys(v, [...prefix, String(i)], out, nodes, values),
    );
    return out;
  }
  if (typeof node === "object") {
    if (prefix.length > 0) {
      out.push(prefix.join(".")); // node key (returnObjects)
      nodes.push(prefix.join("."));
    }
    for (const [k, v] of Object.entries(node))
      flatKeys(v, [...prefix, k], out, nodes, values);
  }
  return out;
}

/** ns -> lang -> Map of leaf key -> its string value. Needed because a
 *  `{{count}}` interpolation lives in the value, and the plural contract is
 *  about which values carry one. */
const catalogValues = new Map();

function addCatalog(ns, lang, keys, nodes, values) {
  if (!catalogs.has(ns)) catalogs.set(ns, new Map());
  const byLang = catalogs.get(ns);
  if (!byLang.has(lang)) byLang.set(lang, new Set());
  const set = byLang.get(lang);
  for (const k of keys) set.add(k);
  if (!nodeKeys.has(ns)) nodeKeys.set(ns, new Set());
  const nodeSet = nodeKeys.get(ns);
  for (const n of nodes) nodeSet.add(n);

  if (!catalogValues.has(ns)) catalogValues.set(ns, new Map());
  const valuesByLang = catalogValues.get(ns);
  if (!valuesByLang.has(lang)) valuesByLang.set(lang, new Map());
  const valueMap = valuesByLang.get(lang);
  for (const [k, v] of values) valueMap.set(k, v);
}

function loadCatalogs() {
  // Core: src/i18n/locales/<lang>/<ns>.json
  const localesDir = resolve(SRC, "i18n/locales");
  for (const lang of LANGUAGES) {
    const langDir = join(localesDir, lang);
    if (!existsSync(langDir)) continue;
    for (const file of readdirSync(langDir)) {
      if (!file.endsWith(".json")) continue;
      const ns = basename(file, ".json");
      const data = JSON.parse(readFileSync(join(langDir, file), "utf8"));
      const keys = [];
      const nodes = [];
      const values = [];
      flatKeys(data, [], keys, nodes, values);
      addCatalog(ns, lang, keys, nodes, values);
    }
  }
  // Modules: src/modules/<mod>/i18n/<lang>.json  → namespace <mod>
  for (const root of SOURCE_ROOTS) {
    const modulesDir = resolve(root, "modules");
    if (!existsSync(modulesDir)) continue;
    for (const mod of readdirSync(modulesDir)) {
      const i18nDir = join(modulesDir, mod, "i18n");
      if (!existsSync(i18nDir)) continue;
      for (const file of readdirSync(i18nDir)) {
        const m = file.match(/^(\w+)\.json$/);
        if (!m || !LANGUAGES.includes(m[1])) continue;
        const data = JSON.parse(readFileSync(join(i18nDir, file), "utf8"));
        const keys = [];
        const nodes = [];
        const values = [];
        flatKeys(data, [], keys, nodes, values);
        addCatalog(mod, m[1], keys, nodes, values);
      }
    }
  }
}

const knownNamespaces = () => new Set(catalogs.keys());

/**
 * ns -> Map of plural-family base -> Set of suffixes present, counting only
 * genuine families (at least TWO distinct plural forms of the same base).
 * Without the >=2 rule a standalone leaf like `attachments.type_other` would
 * collapse to a phantom `attachments.type` base.
 */
function collectPluralFamilies() {
  const out = new Map();
  for (const [ns, byLang] of catalogs) {
    const formsByBase = new Map();
    for (const keys of byLang.values()) {
      for (const key of keys) {
        for (const s of PLURAL_SUFFIXES) {
          if (key.endsWith(s)) {
            const base = key.slice(0, -s.length);
            if (!formsByBase.has(base)) formsByBase.set(base, new Set());
            formsByBase.get(base).add(s);
            break;
          }
        }
      }
    }
    for (const [base, forms] of formsByBase) {
      if (forms.size < 2) formsByBase.delete(base);
    }
    out.set(ns, formsByBase);
  }
  return out;
}

/** Collapse a leaf key onto its plural-family base, or return it unchanged. */
function collapseToPluralBase(families, key) {
  for (const s of PLURAL_SUFFIXES) {
    if (key.endsWith(s)) {
      const base = key.slice(0, -s.length);
      if (families.has(base)) return base;
      break;
    }
  }
  return key;
}

function catalogHas(ns, lang, key) {
  const set = catalogs.get(ns)?.get(lang);
  if (!set) return false;
  if (set.has(key)) return true;
  return PLURAL_SUFFIXES.some((s) => set.has(key + s));
}

function pluralFormsPresent(ns, lang, key) {
  const set = catalogs.get(ns)?.get(lang);
  if (!set) return [];
  return PLURAL_SUFFIXES.filter((s) => set.has(key + s)).map((s) => s.slice(1));
}

// ---------------------------------------------------------------------------
// Code scanning
// ---------------------------------------------------------------------------

/**
 * Extract per-file translation hooks and t() call sites.
 * Returns { calls: [{ns, key, line, hasCount, raw}], dynamic: [{line, raw}] }
 */
function stripComments(text) {
  // Remove block and line comments while preserving line count, without
  // being fooled by comment-like sequences inside strings — e.g. the glob in
  // `accept="image/*"` used to open a fake block comment that blanked every
  // t() call up to the next real `*/`. Uses a small state machine tracking
  // string / template-literal / comment states (templates track ${} depth).
  let out = "";
  let i = 0;
  const n = text.length;
  let state = "code"; // code | line | block | sq | dq | tpl
  let tplBraceDepth = 0;
  const tplStack = [];
  while (i < n) {
    const c = text[i];
    const next = text[i + 1];
    if (state === "line") {
      if (c === "\n") {
        out += c;
        state = "code";
      } else {
        out += " ";
      }
      i++;
    } else if (state === "block") {
      if (c === "*" && next === "/") {
        out += "  ";
        i += 2;
        state = "code";
      } else {
        out += c === "\n" ? "\n" : " ";
        i++;
      }
    } else if (state === "sq" || state === "dq") {
      out += c;
      if (c === "\\") {
        out += next ?? "";
        i += 2;
      } else {
        if ((state === "sq" && c === "'") || (state === "dq" && c === '"'))
          state = "code";
        i++;
      }
    } else if (state === "tpl") {
      out += c;
      if (c === "\\") {
        out += next ?? "";
        i += 2;
      } else if (c === "`") {
        state = "code";
        i++;
      } else if (c === "$" && next === "{") {
        out += "{";
        tplStack.push(tplBraceDepth);
        tplBraceDepth = 1;
        state = "code";
        i += 2;
      } else {
        i++;
      }
    } else {
      // code
      if (c === "/" && next === "/") {
        out += "  ";
        i += 2;
        state = "line";
      } else if (c === "/" && next === "*") {
        out += "  ";
        i += 2;
        state = "block";
      } else if (c === "'") {
        out += c;
        i++;
        state = "sq";
      } else if (c === '"') {
        out += c;
        i++;
        state = "dq";
      } else if (c === "`") {
        out += c;
        i++;
        state = "tpl";
      } else if (c === "{") {
        out += c;
        tplBraceDepth++;
        i++;
      } else if (c === "}" && tplBraceDepth > 0) {
        out += c;
        tplBraceDepth--;
        if (tplBraceDepth === 0 && tplStack.length > 0) {
          tplBraceDepth = tplStack.pop();
          state = "tpl";
        }
        i++;
      } else {
        out += c;
        i++;
      }
    }
  }
  return out;
}

/**
 * The text of a call's arguments, from just past the comma that follows the
 * key to the parenthesis that closes the call — or null if the file ends
 * first.
 *
 * A regular expression cannot do this. `[^)]*` stops at the first `)` it
 * meets, which in `t("a", { unit: x ?? t("b") })` belongs to the inner call,
 * so the arguments read as truncated. Quotes are tracked because a `)` inside
 * a string closes nothing.
 */
function callArguments(text, start) {
  let depth = 1;
  let quote = null;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "(" || ch === "[" || ch === "{") depth++;
    else if (ch === ")" || ch === "]" || ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i);
    }
  }
  return null;
}

/**
 * The arguments after a leading string or template literal, or null when the
 * text does not start with one.
 *
 * i18next accepts `t(key, defaultValue, options)`, so a literal second
 * argument is only a defect when nothing follows it -- nine of the twelve
 * calls the placeholder rule first reported were this legitimate three-
 * argument form, correctly interpolating.
 */
function pastLiteral(text) {
  const body = text.replace(/^\s+/, "");
  const quote = body[0];
  if (quote !== '"' && quote !== "'" && quote !== "`") return null;
  let depth = 0;
  for (let i = 1; i < body.length; i++) {
    const ch = body[i];
    if (ch === "\\") {
      i++;
      continue;
    }
    // `${...}` inside a template literal may itself hold quotes and braces.
    if (quote === "`" && ch === "$" && body[i + 1] === "{") {
      depth++;
      i++;
      continue;
    }
    if (depth > 0) {
      if (ch === "{") depth++;
      else if (ch === "}") depth--;
      continue;
    }
    if (ch === quote) return body.slice(i + 1);
  }
  return null;
}

function scanFile(file) {
  const text = stripComments(readFileSync(file, "utf8"));
  const lines = text.split(/\r?\n/);
  const calls = [];
  const dynamic = [];
  /**
   * Calls whose namespace this scanner had to guess.
   *
   * A file that calls `useTranslation()` states which namespaces its `t`
   * carries. A file that receives `t` as a prop states nothing: the caller
   * decides, and the scanner's fallback to `common` is a guess that happens
   * to be right often enough to hide the times it is not. In
   * `PurchasePatternsGrid` the parent passed `tFor("stats")`, four labels
   * asked for `analytics.patterns.*` with no prefix, i18next looked in
   * `stats`, found nothing, and rendered the English `defaultValue` beside
   * Polish headings — while this gate reported zero missing keys, because
   * `common` does hold those keys.
   *
   * The rule that closes it: a file that does not own its translator must
   * say which namespace each key belongs to.
   */
  const unqualified = [];

  // 1. Find useTranslation aliases and their namespaces.
  //    Maps local t-function name -> namespaces array.
  const fnNamespaces = new Map(); // e.g. "t" -> ["common"], "tScan" -> ["scan"]

  // const { t } = useTranslation("ns")  |  const { t: tX } = useTranslation(["a","b"])
  const hookRe =
    /(?:const\s*\{\s*t(?:\s*:\s*(\w+))?\s*\}\s*=\s*)?useTranslation\(\s*(?:\[([^\]]*)\]|"([^"]+)")?\s*\)/g;
  let m;
  let defaultHookSeen = false;
  let anyHookSeen = false;
  while ((m = hookRe.exec(text)) !== null) {
    anyHookSeen = true;
    const alias = m[1] || "t";
    let namespaces;
    if (m[2] !== undefined) {
      namespaces = [...m[2].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
    } else if (m[3] !== undefined) {
      namespaces = [m[3]];
    } else {
      namespaces = [DEFAULT_NS];
    }
    fnNamespaces.set(alias, namespaces);
    if (alias === "t") defaultHookSeen = true;
  }
  if (!defaultHookSeen && !fnNamespaces.has("t"))
    fnNamespaces.set("t", [DEFAULT_NS]);

  // makeTDynamic(t) only relaxes the key's TYPE — the wrapped function keeps
  // the namespaces of the `t` it was built from, so its static call sites are
  // as resolvable as t()'s. Without this they read as unreferenced and the
  // --unused sweep offers live keys up for deletion.
  const wrapRe = /\b(?:const|let)\s+(\w+)\s*=\s*makeTDynamic\(\s*(\w+)\s*\)/g;
  while ((m = wrapRe.exec(text)) !== null) {
    const source = fnNamespaces.get(m[2]);
    if (source) fnNamespaces.set(m[1], source);
  }

  // 2. Find t()/tAlias() call sites with static string keys.
  const fnNames = [...fnNamespaces.keys()];
  if (fnNames.length === 0) return { calls, dynamic, unqualified };
  //    The pattern stops at the key; the arguments are read by
  //    `callArguments`, and the scan resumes just past the opening
  //    parenthesis so a `t()` sitting inside those arguments is found as a
  //    call of its own.
  const callRe = new RegExp(
    `\\b(${fnNames.join("|")})\\(\\s*(\`[^\`]*\`|"([^"]{1,200})"|'([^']{1,200})')\\s*(,|\\))`,
    "g",
  );

  while ((m = callRe.exec(text)) !== null) {
    const fn = m[1];
    const rawKeyExpr = m[2];
    const opts =
      m[5] === "," ? (callArguments(text, callRe.lastIndex) ?? "") : "";
    const line = text.slice(0, m.index).split("\n").length;
    // Resume inside the call, not after it. `[^)]*` used to swallow the
    // arguments up to the first `)` — the one belonging to a nested call —
    // so `t("a", { unit: x ?? t("b") })` reported `a` and never looked at
    // `b`, which is how a key reached the screen as its own name.
    callRe.lastIndex = m.index + fn.length + 1;

    if (rawKeyExpr.startsWith("`")) {
      dynamic.push({ line, raw: rawKeyExpr.slice(0, 60) });
      continue;
    }
    let key = m[3] ?? m[4];
    if (!key) continue;

    // Namespace resolution.
    let namespaces = fnNamespaces.get(fn) || [DEFAULT_NS];
    const nsOpt = opts.match(/\bns\s*:\s*"([^"]+)"/);
    let stated = false;
    if (nsOpt) {
      namespaces = [nsOpt[1]];
      stated = true;
    } else if (key.includes(":")) {
      const [prefix, rest] = key.split(/:(.+)/);
      if (knownNamespaces().has(prefix)) {
        namespaces = [prefix];
        key = rest;
        stated = true;
      }
    }

    if (!anyHookSeen && !stated) {
      unqualified.push({ line, key: m[3] ?? m[4], fn });
    }

    calls.push({
      ns: namespaces[0],
      fallbacks: namespaces.slice(1),
      key,
      line,
      hasCount: /\bcount\s*(:|\})/.test(opts),
      returnObjects: /\breturnObjects\s*:\s*true/.test(opts),
      // i18next reads a string second argument as a DEFAULT VALUE, never as
      // interpolation. A call that passes one and nothing else hands the
      // translation no variables at all -- harmless until the key's value
      // carries a placeholder, at which point the placeholder reaches the
      // screen verbatim. recordCall() decides; here we only record the shape.
      literalDefault: (() => {
        // The trailing comma is prettier's, not an argument.
        const rest = pastLiteral(opts);
        return rest !== null && rest.trim().replace(/,$/, "").trim() === "";
      })(),
    });
  }

  // 2b. `t(cond ? "a" : "b")` — two static keys behind a ternary. The call
  //     regex above sees neither, so the torch button on the scan screen
  //     announced itself as "torchOn" for as long as the key was missing and
  //     this gate reported nothing at all.
  //     The condition class excludes brackets, not quotes: a condition that
  //     compares against a string of its own — `groupBy === "location"` —
  //     used to drop the whole call out of the measurement, and the register
  //     signed its partner-less group with a raw key while the gate reported
  //     zero missing keys. This is the second time the same shape escaped.
  //     The trailing comma is prettier's, not the author's: a call that does
  //     not fit on one line gets one, and without allowing it here every
  //     multi-line ternary reads as no call at all.
  const ternaryRe = new RegExp(
    `\\b(${fnNames.join("|")})\\(\\s*[^?()]{1,160}\\?\\s*"([^"]{1,200})"\\s*:\\s*"([^"]{1,200})"\\s*,?\\s*\\)`,
    "g",
  );
  while ((m = ternaryRe.exec(text)) !== null) {
    const fn = m[1];
    const line = text.slice(0, m.index).split("\n").length;
    const namespaces = fnNamespaces.get(fn) || [DEFAULT_NS];
    for (const branch of [m[2], m[3]]) {
      let key = branch;
      let ns = namespaces[0];
      let rest = namespaces.slice(1);
      if (key.includes(":")) {
        const [prefix, tail] = key.split(/:(.+)/);
        if (knownNamespaces().has(prefix)) {
          ns = prefix;
          key = tail;
          rest = [];
        }
      }
      calls.push({
        ns,
        fallbacks: rest,
        key,
        line,
        hasCount: false,
        returnObjects: false,
      });
    }
  }

  // 2c. `t(TABLE[expr])` — the keys are a constant map, usually a few lines
  //     up in the same file. The scanner used to see no key at all here and
  //     say so in its own summary ("159 dynamic keys (skipped)"), which is how
  //     three of the six expiry-forecast tiles reached the screen reading
  //     DASHBOARD.TODAY while the gate reported zero missing keys.
  //     Reading the table is pattern recognition rather than a demand that
  //     every key be a literal at the call site: the mapping IS the purpose of
  //     the file's constant, and forbidding it would only push the same lookup
  //     into a shape the scanner likes less. A table it cannot find still
  //     counts as dynamic, exactly as before.
  const tableRe = new RegExp(
    `\\b(${fnNames.join("|")})\\(\\s*([A-Z][A-Z0-9_]*)\\s*\\[`,
    "g",
  );
  while ((m = tableRe.exec(text)) !== null) {
    const fn = m[1];
    const table = m[2];
    const line = text.slice(0, m.index).split("\n").length;
    const args = callArguments(text, m.index + fn.length + 1) ?? "";
    const nsOpt = args.match(/\bns\s*:\s*"([^"]+)"/);

    const decl = new RegExp(
      `\\b(?:const|let)\\s+${table}\\b[^=]*=\\s*\\{`,
    ).exec(text);
    if (!decl) {
      dynamic.push({ line, raw: `${table}[…]` });
      continue;
    }
    const body = callArguments(text, decl.index + decl[0].length);
    if (body === null) {
      dynamic.push({ line, raw: `${table}[…]` });
      continue;
    }

    const valueRe = /:\s*"([^"\n]{1,200})"/g;
    let v;
    while ((v = valueRe.exec(body)) !== null) {
      let key = v[1];
      let ns = nsOpt ? nsOpt[1] : (fnNamespaces.get(fn) || [DEFAULT_NS])[0];
      let fallbacks = nsOpt
        ? []
        : (fnNamespaces.get(fn) || [DEFAULT_NS]).slice(1);
      if (key.includes(":")) {
        const [prefix, rest] = key.split(/:(.+)/);
        if (knownNamespaces().has(prefix)) {
          ns = prefix;
          key = rest;
          fallbacks = [];
        }
      }
      calls.push({
        ns,
        fallbacks,
        key,
        line,
        hasCount: false,
        returnObjects: false,
        literalDefault: false,
      });
    }
  }

  // 3. Key literals carried as data (label:/labelKey:/placeholder:/…). These
  //    never appear at a t() call site — a generic renderer translates them
  //    later — so they need their own pass, otherwise they read as orphans.
  const rel = relative(ROOT, file);
  const literalNs = KEY_LITERAL_NAMESPACES.find((e) => e.file === rel);
  //    Only object properties (`label: "…"`) and field assignments
  //    (`fieldDef.label = "…"`) count. A JSX attribute (`placeholder="…"`) is
  //    literal text shown to the user, not a key to look up.
  const props = KEY_LITERAL_PROPS.join("|");
  const literalRe = new RegExp(
    `(?:\\b(?:${props}):|\\.(?:${props})\\s+=)\\s*"([^"\\n]{1,120})"`,
    "g",
  );
  while ((m = literalRe.exec(text)) !== null) {
    let key = m[1];
    if (!looksLikeI18nKey(key)) continue;

    let namespaces;
    if (key.includes(":")) {
      const [prefix, rest] = key.split(/:(.+)/);
      if (!knownNamespaces().has(prefix)) continue;
      namespaces = [prefix];
      key = rest;
    } else if (literalNs) {
      namespaces = literalNs.namespaces;
    } else if (anyHookSeen) {
      namespaces = fnNamespaces.get("t");
    } else {
      // No namespace to attribute the key to — guessing would manufacture
      // violations, so leave it to the file's own useTranslation() or an
      // explicit KEY_LITERAL_NAMESPACES entry.
      continue;
    }

    calls.push({
      ns: namespaces[0],
      fallbacks: namespaces.slice(1),
      key,
      line: text.slice(0, m.index).split("\n").length,
      hasCount: false,
      returnObjects: false,
    });
  }

  return { calls, dynamic, unqualified };
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(full, out);
    } else if (/\.(tsx?|jsx?)$/.test(entry.name)) {
      if (SKIP_PATH_PARTS.some((p) => full.includes(p))) continue;
      out.push(full);
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

loadCatalogs();
const backendKeys = loadBackendKeys();

const violations = []; // {file, line, ns, key, missingIn[]}
const pluralWarnings = []; // {file, line, ns, key, present[]}
const unqualifiedCalls = []; // {file, line, key} — namespace left to a guess
const placeholderDefaults = []; // {file, line, ns, key} — {{…}} with nothing to fill it

/**
 * Keys whose placeholder is filled by the component that receives the string,
 * not by the t() call -- the one shape the structural rule below cannot see.
 * Each entry names who does the filling; a key without a filler belongs in the
 * report, not here.
 */
const PLACEHOLDER_FILLED_DOWNSTREAM = new Map([
  [
    "approvals:workflows.useCustomRole",
    "SearchableCombobox substitutes {{query}} with the typed text",
  ],
]);
const dynamicKeys = [];
const usedKeys = new Set(); // "ns:key" resolved from static t() calls
/** ns -> [keys] consumed via t(key, { returnObjects: true }) — the call
 * resolves the whole subtree, so every leaf under it counts as used. */
const returnObjectsKeys = new Map();
let scannedCalls = 0;

for (const file of SOURCE_ROOTS.flatMap((root) => walk(root))) {
  const rel = relative(ROOT, file);
  const { calls, dynamic, unqualified } = scanFile(file);
  dynamicKeys.push(...dynamic.map((d) => ({ file: rel, ...d })));
  unqualifiedCalls.push(...unqualified.map((u) => ({ file: rel, ...u })));

  // Module manifests declare page-header / nav keys as plain string literals
  // (titleKey: "recipes:page.title", labelKey: "warehouse:putaway.nav_label")
  // consumed by the shell via useModulePageHeader()/tDyn — never via t() call
  // sites. Without this the --unused scan flags live manifest keys as orphans.
  if (/^src\/modules\/[^/]+\/module\.ts$/.test(rel)) {
    const manifestRe = /\b\w*[Kk]ey\s*:\s*"([A-Za-z0-9_]+):([A-Za-z0-9_.]+)"/g;
    const text = stripComments(readFileSync(file, "utf8"));
    let mm;
    while ((mm = manifestRe.exec(text)) !== null) {
      usedKeys.add(`${mm[1]}:${mm[2]}`);
    }
  }

  for (const call of calls) {
    scannedCalls++;
    recordCall(rel, call);
  }
}

// Backend module manifests declare frontend keys for the module settings form
// and the RBAC matrix — real references the frontend scanner cannot see.
for (const declared of backendKeys) {
  const [ns, key] = declared.split(/:(.+)/);
  recordCall(relative(ROOT, BACKEND_KEYS_PATH), {
    ns,
    fallbacks: [],
    key,
    line: 0,
    hasCount: false,
    returnObjects: false,
  });
}

/** Mark one reference as used and check that every language can serve it. */
function recordCall(rel, call) {
  usedKeys.add(`${call.ns}:${call.key}`);
  // i18next tries fallback namespaces from useTranslation(["a","b"]) — a
  // key may live only in the fallback catalog, so mark it used there too
  // (otherwise --unused deletes live fallback copies).
  for (const fb of call.fallbacks) usedKeys.add(`${fb}:${call.key}`);
  if (call.returnObjects) {
    if (!returnObjectsKeys.has(call.ns)) returnObjectsKeys.set(call.ns, []);
    returnObjectsKeys.get(call.ns).push(call.key);
  }
  // A bare key resolves against the FIRST namespace of useTranslation([...])
  // and nothing else: i18next loads the rest, but searches them only when
  // `fallbackNS` is configured, and this installation does not configure it.
  // Reading the list as a search order is how three keys reached the screen as
  // their own names — `toasts.archivedLabelFreed` in a toast, `torchOn` on a
  // button — each with a complete set of five translations sitting one
  // namespace away.
  // `t("templates.confirm_delete", `Delete template "${tpl.name}"?`)` reads
  // as an author asking for the record's name and getting the placeholder
  // instead: the second argument is a default value, the key exists in all
  // five catalogs so the default never runs, and nothing was passed to fill
  // `{{name}}`. Three delete dialogs shipped asking to confirm the removal of
  // a record called `{{name}}`. The tell is structural -- a value with a
  // placeholder reached by a call whose only other argument is a literal --
  // so it is checkable, and this is where the catalog values already are.
  const englishValue = catalogValues.get(call.ns)?.get("en")?.get(call.key);
  if (
    call.literalDefault &&
    englishValue &&
    /\{\{/.test(englishValue) &&
    !PLACEHOLDER_FILLED_DOWNSTREAM.has(`${call.ns}:${call.key}`)
  ) {
    placeholderDefaults.push({
      file: rel,
      line: call.line,
      ns: call.ns,
      key: call.key,
      value: englishValue,
    });
  }

  const missingIn = LANGUAGES.filter(
    (lang) => !catalogHas(call.ns, lang, call.key),
  );
  if (missingIn.length > 0) {
    violations.push({
      file: rel,
      line: call.line,
      ns: call.ns,
      key: call.key,
      missingIn,
    });
  } else if (call.hasCount) {
    // Plural completeness: PL needs one/few/many for CLDR paucal forms.
    // A key stored as a plain string counts as "no forms at all" — that is
    // the "Zwrócono 2 zasobów" bug class, and it used to slip through
    // because the check only looked at keys that already had some forms.
    const forms = pluralFormsPresent(call.ns, "pl", call.key);
    if (!(forms.includes("one") && forms.includes("few"))) {
      pluralWarnings.push({
        file: rel,
        line: call.line,
        lang: "pl",
        ns: call.ns,
        key: call.key,
        missing: ["_one", "_few", "_many", "_other"]
          .filter((suffix) => !forms.includes(suffix.slice(1)))
          .join(","),
      });
    }
  }
}

/**
 * Plural forms a language must carry for a `{{count}}` value.
 *
 * The base key stays as a fallback for callers that omit `count`; what has to
 * exist alongside it are the CLDR variants, or i18next hands back the base and
 * renders "1 pozycji" / "1 lines".
 */
const REQUIRED_PLURAL_FORMS = {
  en: ["_one", "_other"],
  de: ["_one", "_other"],
  fr: ["_one", "_other"],
  es: ["_one", "_other"],
  pl: ["_one", "_few", "_many", "_other"],
};

/**
 * Every `{{count}}` leaf in every catalog, in every language.
 *
 * This used to be two mechanisms with one blind spot each. The call-site
 * check above sees every namespace but only Polish, and only keys a static
 * `t(..., { count })` reaches — a key handed to a generic renderer is
 * invisible to it. `countPluralContract.test.ts` saw all five languages and
 * whole catalogs, but imported three module catalogs by hand, which is how
 * `launcher.actionItems.subtitle` shipped with a bare `{{count}}`. One sweep,
 * both breadths, and the file-by-file import list is gone.
 */
function sweepCatalogPlurals() {
  for (const [ns, byLang] of catalogValues) {
    for (const [lang, values] of byLang) {
      const required = REQUIRED_PLURAL_FORMS[lang];
      if (!required) continue;
      const present = catalogs.get(ns)?.get(lang) ?? new Set();

      for (const [key, value] of values) {
        if (!value.includes("{{count}}")) continue;
        if (PLURAL_SUFFIXES.some((suffix) => key.endsWith(suffix))) continue;

        // "1 line(s)" is a plural spelled by hand, and it is what the reader
        // sees whenever a caller forgets `count`. It travels with a missing
        // variant often enough to be the same finding.
        const shorthand = /\([a-z]{1,2}\)/i.test(value);
        const missing = required.filter((suffix) => !present.has(key + suffix));
        if (missing.length === 0 && !shorthand) continue;

        pluralWarnings.push({
          file: `${lang}/${ns}.json`,
          line: 0,
          lang,
          ns,
          key,
          missing: missing.length
            ? missing.join(",")
            : `variants instead of "(s)"`,
        });
      }
    }
  }
}

sweepCatalogPlurals();

/**
 * A number followed by a word it cannot inflect.
 *
 * i18next picks a plural form from `count` and from nothing else, so a
 * sentence spelling its number `{{done}}` renders the same words for 1, 2 and
 * 5 — "1 udanych, 1 błędów". The check looks for a count-like interpolation
 * *followed by a word*, which is where the inflection would have to happen:
 * "Wykonano {{done}} / Plan {{expected}}" has no word to inflect and is fine
 * as one string, while "{{done}} udanych" is the bug.
 *
 * The name list is deliberately short — names that only ever hold a bare
 * tally. `number` is usually a document number and `qty` travels with its
 * unit; including them would drown the finding in noise.
 */
const COUNT_LIKE_BEFORE_WORD = new RegExp(
  "\\{\\{\\s*(" +
    [
      "count",
      "done",
      "errors",
      "failed",
      "succeeded",
      "skipped",
      "created",
      "updated",
      "copied",
      "imported",
    ].join("|") +
    ")\\s*\\}\\}\\s+\\p{L}",
  "gu",
);

function sweepCountLikeInterpolations() {
  for (const [ns, byLang] of catalogValues) {
    for (const [lang, values] of byLang) {
      if (!REQUIRED_PLURAL_FORMS[lang]) continue;
      for (const [key, value] of values) {
        const found = [...value.matchAll(COUNT_LIKE_BEFORE_WORD)].map(
          (m) => m[1],
        );
        if (found.length === 0) continue;
        const inert = found.filter((name) => name !== "count");
        if (inert.length === 0 && found.length < 2) continue;

        pluralWarnings.push({
          file: `${lang}/${ns}.json`,
          line: 0,
          lang,
          ns,
          key,
          missing:
            found.length > 1
              ? `two numbers in one sentence (${found.join(", ")}) — split them into separate keys`
              : `number "${found[0]}" does not inflect the word after it — name it count`,
        });
      }
    }
  }
}

sweepCountLikeInterpolations();

// One finding per key, whichever mechanism raised it first: the same key seen
// from a call site and from four catalogs is one thing to fix.
{
  const seen = new Set();
  for (let i = pluralWarnings.length - 1; i >= 0; i--) {
    const id = `${pluralWarnings[i].ns}:${pluralWarnings[i].key}`;
    if (seen.has(id)) pluralWarnings.splice(i, 1);
    else seen.add(id);
  }
  pluralWarnings.sort((a, b) =>
    `${a.ns}:${a.key}`.localeCompare(`${b.ns}:${b.key}`),
  );
}

// ---------------------------------------------------------------------------
// A Polish key naming a unit the English source does not
// ---------------------------------------------------------------------------
//
// "Ile sztuk \"Jabłka Fuji\" chcesz usunąć? (dostępne 7.900 kg)" asked for
// pieces and answered in kilograms in the same sentence. The English source
// said "How many of ... would you like to remove?" — neutral about the unit,
// and correct, because the unit arrives with the row's data ({{uom}}). The
// Polish translation had invented one, and it invented it in a catalogue,
// where no code review and no other gate could see it: the key existed, was
// used, and was not a raw string, so `check:i18n` and `lint-i18n-raw` both
// stayed green by design.
//
// The rule is narrow on purpose, and only Polish is checked because Polish is
// where the class was measured: a pl value carrying a unit noun ("szt",
// "szt.", "sztuka/sztuki/sztukę/...") whose en value in the same key carries
// no unit word. English "piece/unit/pcs/each" in the source is the licence to
// name one in the translation. Widening it (every language, every unit noun,
// "jednostka") is a decision with its own measurements, not a free extension
// of this one — "sztuczny" would match a naive `\bszt\w*`, which is why only
// the abbreviation and the "sztuk-" stem are matched.
const PL_UNIT_NOUN = /\bszt\.?(?=\s|$)|\bsztuk\w*/iu;
const EN_UNIT_WORD = /\b(?:piece|pieces|unit|units|pcs|pc|each)\b/iu;

const unitNounFindings = []; // {ns, key}

function sweepUnitNounFidelity() {
  for (const [ns, byLang] of catalogValues) {
    const en = byLang.get("en");
    const pl = byLang.get("pl");
    if (!en || !pl) continue;
    for (const [key, value] of pl) {
      if (!PL_UNIT_NOUN.test(value)) continue;
      const source = en.get(key);
      if (source === undefined || EN_UNIT_WORD.test(source)) continue;
      unitNounFindings.push({ ns, key });
    }
  }
  unitNounFindings.sort((a, b) =>
    `${a.ns}:${a.key}`.localeCompare(`${b.ns}:${b.key}`),
  );
}

sweepUnitNounFidelity();

// ---------------------------------------------------------------------------
// A name left in English: the pair, not the value
// ---------------------------------------------------------------------------
//
// Everything above passes a screen title nobody translated. The key exists in
// all five catalogs (parity holds), it is a string (the plural rules look
// elsewhere), and it is referenced by code (so it is not an orphan). Only the
// pair is a finding: the value identical to English while the four sibling
// catalogs say something of their own. "Picking" in pl.json sat beside
// "Kommissionierung", "Préparation" and "Recogida", and the screen whose own
// action reads "Skompletuj pozycje" announced itself in English to a Polish
// reader — and to a screen reader, through the aria-label of the whole sheet.
//
// Scoped to the names of things. Polish borrows field labels wholesale
// (Model, VAT, Email, Manager, Reset, Timer, Gram, Kilogram) and a rule that
// flags those fires seventeen times on this tree to catch the one real case —
// a gate with that ratio gets switched off, and the switch is what leaves the
// next "Picking" in place. A screen's name is the one string the module's own
// vocabulary already covers.
// ---------------------------------------------------------------------------
// Three dots where the catalogue has one character
// ---------------------------------------------------------------------------
//
// A placeholder trails off in one glyph: U+2026. Three periods wrap as three,
// are cut as three when a line is truncated, and some screen readers say "dot
// dot dot" instead of nothing. The two spellings were mixed almost evenly in
// every language when this was written — 32 against 23 in Polish and the same
// split in English, the same count in both, which is what a convention nobody
// wrote down looks like: the translation copied whatever the source carried.
//
// Scoped to the catalogues. A `...` in code is a spread or an example, and
// UI_GUIDELINES.md §14.5 states the rule the catalogues keep.
const THREE_DOTS = /\.\.\./;

function sweepThreeDots() {
  const findings = []; // {ns, lang, key, value}
  for (const [ns, byLang] of catalogValues) {
    for (const [lang, values] of byLang) {
      for (const [key, value] of values) {
        if (THREE_DOTS.test(value)) findings.push({ ns, lang, key, value });
      }
    }
  }
  return findings;
}

const threeDots = sweepThreeDots();

const TITLE_SUFFIXES = ["title", "subtitle", "heading"];
const SIBLING_LANGS = ["de", "fr", "es"];

// A screen's name is not always the whole last segment: `summary_title`,
// `page_title` and `modalTitle` name a heading just as `title` does, and the
// rule used to see only the bare word. The suffix must start a word (after `_`
// or a camelCase hump), so `subtitle` and `untitled` stay what they were.
const TITLE_KEY_SUFFIX = new RegExp(
  `(^|_)(${TITLE_SUFFIXES.join("|")})$|[a-z](${TITLE_SUFFIXES.map(
    (s) => s[0].toUpperCase() + s.slice(1),
  ).join("|")})$`,
);

// i18next plural forms hang a category on the key (`title_one`, `summary_title_other`);
// the heading is still the word before it.
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

function sweepUntranslatedTitles() {
  const findings = []; // {ns, key, value, siblings}
  for (const [ns, byLang] of catalogs) {
    const enKeys = byLang.get("en");
    if (!enKeys) continue;
    for (const key of enKeys) {
      if (
        !TITLE_KEY_SUFFIX.test(
          (key.split(".").pop() ?? "").replace(PLURAL_SUFFIX, ""),
        )
      )
        continue;
      const value = catalogValues.get(ns)?.get("en")?.get(key);
      const pl = catalogValues.get(ns)?.get("pl")?.get(key);
      if (typeof value !== "string" || typeof pl !== "string") continue;
      if (!value.trim() || pl.trim() !== value.trim()) continue;
      const siblings = {};
      let translated = 0;
      let complete = true;
      for (const lang of SIBLING_LANGS) {
        const other = catalogValues.get(ns)?.get(lang)?.get(key);
        if (typeof other !== "string") {
          complete = false;
          break;
        }
        siblings[lang] = other;
        if (other.trim() !== value.trim()) translated += 1;
      }
      if (!complete || translated !== SIBLING_LANGS.length) continue;
      findings.push({ ns, key, value, siblings });
    }
  }
  findings.sort((a, b) => `${a.ns}:${a.key}`.localeCompare(`${b.ns}:${b.key}`));
  return findings;
}

const untranslatedTitles = sweepUntranslatedTitles();

// ---------------------------------------------------------------------------
// Plural families: what a change did to the sisters
// ---------------------------------------------------------------------------
//
// Everything above checks that plural forms EXIST. Presence is not content.
// The location-delete dialog once called the same records by two different
// nouns in one breath: the Polish rewrite touched `_one` and `_other`, the
// forms English thinks in, and left `_few`/`_many` — the forms Polish
// actually speaks for 2 and up — carrying the previous sentence. Every form
// existed, so this gate stayed green, and the row on the screen contradicted
// the dialog beside it.
//
// Content cannot be judged from the tree alone: there is no "wrong sentence",
// only "a sentence half of the family no longer agrees with". So the reference
// is a snapshot — the hash of every form of every plural family, committed in
// scripts/i18n-plural-snapshot.json and refreshed only through its own
// door, --write-plural-snapshot — deliberately separate from the keys
// baseline, so refreshing what keys exist can never absolve what they say. A
// family whose SOME forms moved while the sisters kept their old hash is a
// finding: a sentence whose meaning changed changes in all of its forms, or
// the refresh says out loud that the sisters were meant to stay.

function formHashes(forms) {
  const out = {};
  for (const [form, value] of [...forms.entries()].sort()) {
    out[form] = createHash("sha256")
      .update(String(value))
      .digest("hex")
      .slice(0, 12);
  }
  return out;
}

/** ns -> lang -> Map(base -> Map(form -> value)), families only (>=2 forms). */
function collectPerLanguageFamilies() {
  const out = new Map();
  for (const [ns, byLang] of catalogs) {
    const nsOut = new Map();
    for (const [lang, keys] of byLang) {
      const formsByBase = new Map();
      for (const key of keys) {
        for (const s of PLURAL_SUFFIXES) {
          if (key.endsWith(s)) {
            const base = key.slice(0, -s.length);
            if (!formsByBase.has(base)) formsByBase.set(base, new Map());
            formsByBase
              .get(base)
              .set(
                s.slice(1),
                catalogValues.get(ns)?.get(lang)?.get(key) ?? "",
              );
            break;
          }
        }
      }
      for (const [base, forms] of formsByBase) {
        if (forms.size < 2) formsByBase.delete(base);
      }
      if (formsByBase.size > 0) nsOut.set(lang, formsByBase);
    }
    if (nsOut.size > 0) out.set(ns, nsOut);
  }
  return out;
}

/** The snapshot shape: "ns|lang|base" -> { form: hash }, sorted for a stable diff. */
function snapshotFor(perLangFamilies) {
  const out = {};
  const ids = [];
  for (const [ns, byLang] of perLangFamilies) {
    for (const [lang, formsByBase] of byLang) {
      for (const [base, forms] of formsByBase) {
        ids.push([`${ns}|${lang}|${base}`, forms]);
      }
    }
  }
  ids.sort(([a], [b]) => a.localeCompare(b));
  for (const [id, forms] of ids) out[id] = formHashes(forms);
  return out;
}

function loadPluralSnapshot() {
  if (!existsSync(PLURAL_SNAPSHOT_PATH)) return null;
  return JSON.parse(readFileSync(PLURAL_SNAPSHOT_PATH, "utf8"));
}

/**
 * Families split mid-sentence: some forms moved since the snapshot, the
 * sisters did not. A dropped or added form neither accuses nor pardons —
 * what damns the family is old wording standing next to new.
 */
function siblingFindings(perLangFamilies, snapshot) {
  const findings = []; // {ns, lang, base, changed, kept}
  for (const [ns, byLang] of perLangFamilies) {
    for (const [lang, formsByBase] of byLang) {
      for (const [base, forms] of formsByBase) {
        const snap = snapshot[`${ns}|${lang}|${base}`];
        if (!snap) continue;
        const now = formHashes(forms);
        const changed = [];
        const kept = [];
        for (const [form, hash] of Object.entries(now)) {
          if (snap[form] === undefined) continue;
          if (snap[form] === hash) kept.push(form);
          else changed.push(form);
        }
        if (changed.length > 0 && kept.length > 0) {
          findings.push({ ns, lang, base, changed, kept });
        }
      }
    }
  }
  findings.sort((a, b) =>
    `${a.ns}|${a.lang}|${a.base}`.localeCompare(`${b.ns}|${b.lang}|${b.base}`),
  );
  return findings;
}

const perLangFamilies = collectPerLanguageFamilies();
const pluralSnapshot = loadPluralSnapshot();
const siblings = pluralSnapshot
  ? siblingFindings(perLangFamilies, pluralSnapshot)
  : [];
if (!pluralSnapshot && !process.argv.includes("--quiet")) {
  console.log(
    "check-i18n-keys: no plural snapshot — run --write-plural-snapshot to start watching what a change does to a family's sisters",
  );
}

/**
 * The tree-state measurement: families whose forms do not share a word.
 *
 * Where the snapshot rule above reads intent from a change, this one reads
 * drift from the finished text: within one language, forms of a family are
 * supposed to be one sentence bending around a number, so their word stems
 * should overlap. Forms that share nothing with the sisters — "zasób/zasobów"
 * beside "rekordy/rekordów" — are two vocabularies in one family. Stems are
 * the first four letters after folding diacritics, which is enough for "zasób
 * / zasobów" and honest about its limits: Polish suppletion (rok → lata,
 * dzień → dni) legitimately shares nothing and will be reported. This is a
 * report, not a gate — the number answers "how much of this is in the tree".
 */
const stemOf = (word) =>
  word.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().slice(0, 4);

function familyStems(forms) {
  const byForm = new Map();
  for (const [form, value] of forms) {
    // The placeholder is every form's common word — "{{count}}" would glue
    // unrelated vocabularies into one family. The sentence around it is what
    // can drift apart.
    const text = String(value).replace(/\{\{[^}]*\}\}/g, " ");
    const stems = new Set(
      [...text.matchAll(/\p{L}{3,}/gu)].map((m) => stemOf(m[0])),
    );
    if (stems.size > 0) byForm.set(form, stems);
  }
  return byForm;
}

function driftFindings(perLangFamilies, lang) {
  const findings = []; // {ns, base, groups}
  for (const [ns, byLang] of perLangFamilies) {
    const formsByBase = byLang.get(lang);
    if (!formsByBase) continue;
    for (const [base, forms] of formsByBase) {
      const byForm = familyStems(forms);
      if (byForm.size < 2) continue;
      // Connected components over shared stems.
      const groups = [];
      for (const [form, stems] of byForm) {
        const touching = groups.filter((g) =>
          g.stems.some((s) => stems.has(s)),
        );
        if (touching.length === 0) {
          groups.push({ forms: [form], stems: [...stems] });
          continue;
        }
        const first = touching[0];
        first.forms.push(form);
        for (const g of touching.slice(1)) {
          first.forms.push(...g.forms);
          first.stems.push(...g.stems);
          groups.splice(groups.indexOf(g), 1);
        }
        for (const s of stems)
          if (!first.stems.includes(s)) first.stems.push(s);
      }
      if (groups.length > 1) {
        findings.push({
          ns,
          base,
          groups: groups.map((g) => g.forms.sort().join("/")),
        });
      }
    }
  }
  findings.sort((a, b) =>
    `${a.ns}:${a.base}`.localeCompare(`${b.ns}:${b.base}`),
  );
  return findings;
}

const drifts = driftFindings(perLangFamilies, "pl");

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

const args = process.argv.slice(2);
const quiet = args.includes("--quiet");
const useBaseline = args.includes("--baseline");
const writeBaseline = args.includes("--write-baseline");
const unusedMode = args.includes("--unused");
const pluralReportMode = args.includes("--plural-report");

const violationId = (v) => `${v.ns}:${v.key}`;
const unqualifiedId = (u) => `${u.file}:${u.key}`;

// Orphan keys (defined but never referenced by the static scanner), only
// computed in --unused mode or when snapshotting the baseline. Reports exact
// LEAF keys (node keys are structural and never reported): a leaf counts as
// used when either the leaf itself or its plural-family base is referenced —
// so genuine dead plural families are reported form by form and can be
// deleted verbatim, while standalone keys that merely end in a plural-ish
// suffix (e.g. `attachments.type_other`, statically called) stay untouched.
let orphans = []; // {ns, key}
if (unusedMode || writeBaseline) {
  const familiesByNs = collectPluralFamilies();
  for (const [ns, byLang] of catalogs) {
    const nodes = nodeKeys.get(ns) ?? new Set();
    const roKeys = returnObjectsKeys.get(ns) ?? [];
    const families = familiesByNs.get(ns) ?? new Map();
    const leafKeys = new Set();
    for (const keys of byLang.values()) {
      for (const key of keys) if (!nodes.has(key)) leafKeys.add(key);
    }
    const roConsumed = (k) =>
      roKeys.some((rk) => k === rk || k.startsWith(`${rk}.`));
    for (const key of leafKeys) {
      const base = collapseToPluralBase(families, key);
      if (
        usedKeys.has(`${ns}:${key}`) ||
        usedKeys.has(`${ns}:${base}`) ||
        isDynamicallyConsumed(ns, key) ||
        isDynamicallyConsumed(ns, base) ||
        roConsumed(key) ||
        roConsumed(base)
      )
        continue;
      orphans.push({ ns, key });
    }
  }
  orphans.sort((a, b) => `${a.ns}:${a.key}`.localeCompare(`${b.ns}:${b.key}`));
}

const baselineData =
  useBaseline && existsSync(BASELINE_PATH)
    ? JSON.parse(readFileSync(BASELINE_PATH, "utf8"))
    : { violations: [], unused: [], unqualified: [] };

// Two artifacts forgive two unrelated things, and they used to share one
// door: `--write-baseline` wrote the keys baseline AND the plural snapshot
// in one breath — so whoever refreshed the baseline for a removed component
// also, without meaning to, absolved a plural-family drift standing in the
// tree at that moment. Each artifact now has its own door.
const writePluralSnapshot = args.includes("--write-plural-snapshot");

if (writeBaseline || writePluralSnapshot) {
  let snapshotSummary = "";
  if (writePluralSnapshot) {
    const snapshot = snapshotFor(perLangFamilies);
    if (pluralSnapshot) {
      const drift = siblingFindings(perLangFamilies, pluralSnapshot);
      for (const f of drift) {
        console.error(
          `SIBLINGS ${f.ns}:${f.base}  (${f.lang})  forms ${f.changed.join(",")} changed, ` +
            `${f.kept.join(",")} kept the old wording — the snapshot now takes the new state ` +
            `as the reference; say in the commit why the sisters stay as they are`,
        );
      }
    }
    writeFileSync(
      PLURAL_SNAPSHOT_PATH,
      `${JSON.stringify(snapshot, null, 2)}\n`,
    );
    snapshotSummary = `; plural snapshot: ${Object.keys(snapshot).length} family entries → ${relative(process.cwd(), PLURAL_SNAPSHOT_PATH)}`;
  }
  if (writeBaseline) {
    const ids = [...new Set(violations.map(violationId))].sort();
    const unusedIds = orphans.map((o) => `${o.ns}:${o.key}`);
    const pluralIds = [...new Set(pluralWarnings.map(violationId))].sort();
    const unqualifiedIds = [
      ...new Set(unqualifiedCalls.map(unqualifiedId)),
    ].sort();
    const unitNounIds = unitNounFindings.map(violationId);
    writeFileSync(
      BASELINE_PATH,
      JSON.stringify(
        {
          violations: ids,
          plural: pluralIds,
          unused: unusedIds,
          unqualified: unqualifiedIds,
          unitNoun: unitNounIds,
        },
        null,
        2,
      ) + "\n",
    );
    console.log(
      `baseline written: ${ids.length} violation(s) + ${pluralIds.length} plural gap(s) + ${unusedIds.length} unused key(s) + ${unqualifiedIds.length} unqualified call(s) + ${unitNounIds.length} unit-noun finding(s) → ${relative(process.cwd(), BASELINE_PATH)}` +
        snapshotSummary,
    );
  } else {
    console.log(
      `plural snapshot written${snapshotSummary.replace("; plural snapshot:", ":")}`,
    );
  }
  process.exit(0);
}

/**
 * --plural-report: the tree-state measurement, informational, never a gate.
 * Answers "how many Polish plural families carry two vocabularies" — the
 * drift the snapshot rule catches only once somebody edits the family next.
 */
if (pluralReportMode) {
  for (const d of drifts) {
    console.log(
      `PLURAL-DRIFT ${d.ns}:${d.base}  (pl)  ${d.groups.join(" | ")}`,
    );
  }
  console.log(
    `\nplural-drift: ${drifts.length} Polish plural famil${drifts.length === 1 ? "y" : "ies"} split into groups sharing no word stem ` +
      `(suppletion like rok→lata is a known false positive — read the hits, don't bulk-fix them)`,
  );
  process.exit(0);
}

let effectiveViolations = violations;
let grandfathered = 0;
if (useBaseline) {
  const baseline = new Set(baselineData.violations ?? []);
  grandfathered = violations.filter((v) => baseline.has(violationId(v))).length;
  effectiveViolations = violations.filter((v) => !baseline.has(violationId(v)));
}

// The nineteen keys this class had when it grew teeth are a cleanup of their
// own, not this rule's; they sit in the baseline so the rule blocks the next one
// without blocking the branch that wrote it.
const baselinePlural = new Set(baselineData.plural ?? []);
const grandfatheredPlural = pluralWarnings.filter((w) =>
  baselinePlural.has(violationId(w)),
).length;
const effectivePlurals = useBaseline
  ? pluralWarnings.filter((w) => !baselinePlural.has(violationId(w)))
  : pluralWarnings;

const baselineUnqualified = new Set(baselineData.unqualified ?? []);
const grandfatheredUnqualified = unqualifiedCalls.filter((u) =>
  baselineUnqualified.has(unqualifiedId(u)),
).length;
const effectiveUnqualified = useBaseline
  ? unqualifiedCalls.filter((u) => !baselineUnqualified.has(unqualifiedId(u)))
  : unqualifiedCalls;

const baselineUnused = new Set(baselineData.unused ?? []);
const grandfatheredUnused = orphans.filter((o) =>
  baselineUnused.has(`${o.ns}:${o.key}`),
).length;
const effectiveOrphans = unusedMode
  ? orphans.filter((o) => !baselineUnused.has(`${o.ns}:${o.key}`))
  : [];

const baselineUnitNoun = new Set(baselineData.unitNoun ?? []);
const grandfatheredUnitNoun = unitNounFindings.filter((f) =>
  baselineUnitNoun.has(violationId(f)),
).length;
const effectiveUnitNouns = useBaseline
  ? unitNounFindings.filter((f) => !baselineUnitNoun.has(violationId(f)))
  : unitNounFindings;

if (!quiet) {
  for (const v of effectiveViolations) {
    console.error(
      `MISSING ${v.ns}:${v.key}  (${v.file}:${v.line})  missing in ${v.missingIn.join(",")}`,
    );
  }
  for (const w of effectivePlurals) {
    console.error(
      `PLURAL ${w.ns}:${w.key}  (${w.file})  ${w.lang} missing: ${w.missing}`,
    );
  }
  for (const f of siblings) {
    console.error(
      `SIBLINGS ${f.ns}:${f.base}  (${f.lang})  forms ${f.changed.join(",")} changed, ` +
        `${f.kept.join(",")} kept the old wording`,
    );
  }
  for (const u of effectiveUnqualified) {
    console.error(
      `UNQUALIFIED ${u.key}  (${u.file}:${u.line})  — this file receives its ` +
        `t(); name the namespace ("ns:key" or { ns: "ns" })`,
    );
  }
  for (const p of placeholderDefaults) {
    console.error(
      `PLACEHOLDER ${p.ns}:${p.key}  (${p.file}:${p.line})  "${p.value}" — ` +
        `the second argument to t() is a default value, not an interpolation`,
    );
  }
  for (const t of untranslatedTitles) {
    console.error(
      `UNTRANSLATED ${t.ns}:${t.key}  (pl)  "${t.value}" — the same string as ` +
        `in en, while ${SIBLING_LANGS.map((l) => `${l}:"${t.siblings[l]}"`).join(", ")}`,
    );
  }
  for (const f of threeDots) {
    console.error(
      `ELLIPSIS ${f.lang}/${f.ns}.json  ${f.key}  "${f.value}" — three dots instead of …`,
    );
  }
  for (const o of effectiveOrphans) {
    console.error(`UNUSED ${o.ns}:${o.key}`);
  }
  for (const f of effectiveUnitNouns) {
    console.error(
      `UNIT-NOUN ${f.ns}:${f.key}  (pl)  — the pl string names a unit ` +
        `the English source does not; the unit comes from the item's data, not the catalogue`,
    );
  }
}

console.log(
  `\ncheck-i18n-keys: ${scannedCalls} t() calls | ` +
    `${violations.length} missing keys${useBaseline ? ` (${grandfathered} in baseline)` : ""} | ` +
    `${pluralWarnings.length} missing plural forms${useBaseline ? ` (${grandfatheredPlural} in baseline)` : ""} | ` +
    `${siblings.length} families with a partial form change | ` +
    `${untranslatedTitles.length} screen names left in English | ` +
    `${threeDots.length} strings with "..." instead of "…" | ` +
    `${dynamicKeys.length} dynamic keys (skipped) | ` +
    `${unqualifiedCalls.length} calls without a namespace${useBaseline ? ` (${grandfatheredUnqualified} in baseline)` : ""} | ` +
    `${orphans.length} orphaned keys${unusedMode ? ` (${grandfatheredUnused} in baseline)` : ""} | ` +
    `${unitNounFindings.length} pl unit nouns without a source${useBaseline ? ` (${grandfatheredUnitNoun} in baseline)` : ""}`,
);

if (effectiveViolations.length > 0) {
  console.error(
    `\n✗ ${effectiveViolations.length} new violations — add the keys to the catalogues (×5 languages) or fix the t() call.`,
  );
  process.exit(1);
}
if (effectivePlurals.length > 0) {
  console.error(
    `\n✗ ${effectivePlurals.length} new keys with {{count}} and no plural forms — add the CLDR variants (_one/_other, and _few/_many for pl).`,
  );
  process.exit(1);
}
if (siblings.length > 0) {
  console.error(
    `\n✗ ${siblings.length} plural families changed some of their forms while the sisters kept the old wording — ` +
      `a sentence whose meaning changes changes across the whole family: add the remaining forms to the new wording ` +
      `(or refresh the snapshot with --write-plural-snapshot and say in the commit why the sisters stay).`,
  );
  process.exit(1);
}
if (effectiveUnitNouns.length > 0) {
  console.error(
    `\n✗ ${effectiveUnitNouns.length} pl keys name a unit the English source does not — ` +
      `the unit comes from the item's data ({{uom}}), not the catalogue: drop "sztuk/szt." from the translation ` +
      `or ask the source (en) for it if the sentence really needs it.`,
  );
  process.exit(1);
}
if (effectiveUnqualified.length > 0) {
  console.error(
    `\n✗ ${effectiveUnqualified.length} t() calls in files that receive t() from outside — ` +
      `pass the namespace ("ns:key" or { ns: "ns" }), otherwise the key is looked up in a foreign namespace ` +
      `and silently falls back to defaultValue.`,
  );
  process.exit(1);
}
if (placeholderDefaults.length > 0) {
  console.error(
    `\n✗ ${placeholderDefaults.length} t() calls with a placeholder nothing can fill — ` +
      `pass an interpolation object (t("key", { name })), because the string in the second argument is a default value.`,
  );
  process.exit(1);
}
if (untranslatedTitles.length > 0) {
  console.error(
    `\n✗ ${untranslatedTitles.length} screen names still in English in the pl catalogue, ` +
      `while de/fr/es each have a word of their own there — translate the name (or, if it is a proper name, ` +
      `say in the commit why it stays).`,
  );
  process.exit(1);
}
if (threeDots.length > 0) {
  console.error(
    `\n✗ ${threeDots.length} strings in the catalogues use three dots — \`…\` is a single character, while three dots wrap and clip as three (UI_GUIDELINES §14.5).`,
  );
  process.exit(1);
}
if (effectiveOrphans.length > 0) {
  console.error(
    `\n✗ ${effectiveOrphans.length} new orphaned keys — remove them from the catalogues or add them to DYNAMIC_ALLOWLIST (for dynamic consumption only).`,
  );
  process.exit(1);
}
console.log("✓ no new violations");
