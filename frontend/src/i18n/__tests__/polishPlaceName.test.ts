/**
 * A place is "miejsce" in Polish, and never named with the retired feminine
 * noun it replaced.
 *
 * The rename from "lokalizacja" was done by script, and a script moves words
 * it recognises: the strings that spelled the noun differently ("podlokalizacja")
 * or carried it inside another phrase kept the old name in a product that has
 * stopped using it. The noun itself is mechanical, so it is asserted — no
 * Polish string in any catalogue may name a place with "lokalizacja" or
 * "podlokalizacja".
 *
 * The gender and number of the words around it are not mechanical in general —
 * "pierwszą półkę" is correct Polish, the shelf being feminine. But a form
 * that stands FOR the place cannot agree with anything else: an ordinal,
 * pronoun or adjective with no noun of its own ("Utwórz pierwszy", "Dodaj
 * pierwszą", "Potwierdzić ją jako policzoną i pustą", "zeskanuj jej etykietę"),
 * a feminine predicate under a place's own name ("{{location}} jest pusta"),
 * and a plural genitive joined to singular "miejsca" ("dla produktów i
 * miejsca"). A status label is the same claim one word long ("Pusta",
 * "Zamknięta przez: {{name}}", "Oznacz jako przeterminowaną"): the call site
 * renders it for a place, a partia or an atestacja and the string alone cannot
 * say which, so the label shape sweeps every catalogue and the exception map
 * names the feminine referent of each allowed one. Those are the shapes the
 * sweep corrected and keeps finding, so they are asserted too; the rest stays
 * a reader's question.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(process.cwd(), "src");

/** Every Polish catalogue: the core namespaces and each module's own. */
function polishCatalogues(): Array<[string, unknown]> {
  const files: string[] = [];
  const core = join(SRC, "i18n", "locales", "pl");
  for (const entry of readdirSync(core)) {
    if (entry.endsWith(".json")) files.push(join(core, entry));
  }
  const modulesDir = join(SRC, "modules");
  for (const moduleName of readdirSync(modulesDir)) {
    const path = join(modulesDir, moduleName, "i18n", "pl.json");
    if (existsSync(path)) files.push(path);
  }
  return files.map((file) => [
    file.slice(SRC.length + 1),
    JSON.parse(readFileSync(file, "utf8")) as unknown,
  ]) as Array<[string, unknown]>;
}

/** Every string under `node` that names a place with the retired noun. */
function retiredNames(
  node: unknown,
  path: string[] = [],
): Array<{ key: string; value: string }> {
  const found: Array<{ key: string; value: string }> = [];
  if (typeof node === "string") {
    // A stem match on "lokalizacj" also finds "podlokalizacja": the compound
    // names the same place a level down, and is retired with it.
    if (/lokalizacj/i.test(node)) {
      found.push({ key: path.join("."), value: node });
    }
  } else if (Array.isArray(node)) {
    node.forEach((entry, index) => {
      found.push(...retiredNames(entry, [...path, String(index)]));
    });
  } else if (node && typeof node === "object") {
    for (const [key, value] of Object.entries(node)) {
      found.push(...retiredNames(value, [...path, key]));
    }
  }
  return found;
}

describe("no Polish string names a place with the retired noun", () => {
  it("says miejsce in every catalogue", () => {
    const hits = polishCatalogues().flatMap(([file, catalog]) =>
      retiredNames(catalog).map(
        (hit) => `${file} :: ${hit.key} :: ${hit.value}`,
      ),
    );
    expect(hits).toEqual([]);
  });

  it("would catch a name the rename left behind", () => {
    expect(retiredNames({ count: "{{count}} w podlokalizacjach" })).toEqual([
      { key: "count", value: "{{count}} w podlokalizacjach" },
    ]);
    expect(retiredNames({ title: "Kolejność lokalizacji" })).toEqual([
      { key: "title", value: "Kolejność lokalizacji" },
    ]);
  });
});

/**
 * A form standing where the place stands, still in the old feminine gender or
 * in the number its genitive once took.
 *
 * The follow-set is what makes the form "standing": an ordinal or adjective
 * with a noun of its own agrees with that noun ("pierwszą półkę", "jednej
 * liście") and is correct Polish whatever the noun's gender. Only a form cut
 * off by punctuation, a conjunction or a preposition has the place for its
 * referent — and then feminine "-ą"/"-ej" or masculine "-y" is the old noun's
 * gender, where "miejsce" takes "-e", "-ego", "-ym".
 */
const STATUS_STEMS = `pierwsz|jedn|drug|now|pust|pełn|cał|sam|każd|żadn|inn|dostęp|wybran|gotow|właściw|dowoln|dodatkow|kolejn|policzon|zapisan|dodan|utworzon|przeniesion|zarchiwizowan|usunięt|zmienion|zamknięt|otwart|widoczn|aktywn|wymagan|poprawn|błędn|podobn|podan|wprowadzon|wskazan|określon|jedyn|ostatni|następn|woln|główn|potwierdzon|rozpoczęt|wydrukowan|uży|zuży|przypisan|uruchomion|anulowan|wstrzyman|przeterminowan|wycofan|wznowion|wykonan|częściow|napełnian|oczekiwan|włączon|domyśln|wbudowan|włas|zajęt|przepełnion|odrzucon|zatwierdzon|odwołan|zakończon|zablokowan|zawieszon|nierozpoznan`;

const STANDING_FORM = new RegExp(
  `\\b(?:${STATUS_STEMS})\\w?(?:ą|ej)(?![\\p{L}\\p{N}_])(?=\\s*(?:[,;…?!.]|$)|\\s+(?:i|a|żeby|z|przed|po|w)\\b)|\\b(?:pierwsz|now|drug|sam|gotow|pust|dostęp|wybran)\\w*?(?:y|i)(?![\\p{L}\\p{N}_])(?=\\s*(?:[,;…?!.]|$)|\\s+(?:i|a|żeby|z|przed|po|w)\\b)`,
  "giu",
);

/** "dla produktów i miejsca" — a plural genitive beside a singular one. */
const GENITIVE_LIST = /\b\w+ów\b[^.?!]{0,60}\bi miejsca\b/giu;

/** Feminine pronoun or predicate under the place's own name. `\b` after "ą"
 * never fires — JS word characters are ASCII — so the end of the word is
 * spelled out. */
const FEMININE_PRONOUN = /\b(ją|nią|jej|tę)(?![\p{L}\p{N}_])/giu;
const FEMININE_PREDICATE =
  /\{\{location\}\}[^.?!]{0,60}\b(jest|została|będzie|pozostaje|wydaje się)\s+\w+(?:a|ą)(?![\p{L}\p{N}_])/giu;

/**
 * A status label: the whole value is one word ("Pusta", "Zamknięta",
 * "Zarchiwizowana"), or one word with a "przez …" / "jako …" tail ("Zamknięta
 * przez: {{name}}", "Oznacz jako przeterminowaną"). The tail is still part of
 * the label — the shape refuses anything that names a noun after the word
 * ("Oznacz partię jako przeterminowaną" says "partię" and is right).
 *
 * A label has no noun of its own anywhere in the string: the gender it carries
 * is a claim about whatever the screen labels, and only the call site knows
 * that referent. So the shape sweeps every catalogue and the exception map
 * below names, key by key, the feminine noun each allowed label agrees with —
 * the same way a residue on a place is corrected, a residue on a "partia" or
 * an "atestacja" is recorded. A new label of this shape fails the sweep until
 * it is either corrected or named there.
 */
const LABEL_VALUE = /^\S+(?:\s+(?:jako\b|przez\b).*)?$/u;
const LABEL_WORD = new RegExp(
  `(?:^|\\s)((?:nie)?(?:${STATUS_STEMS})\\w{0,2}(?:a|ą|ej))(?![\\p{L}\\p{N}_])(?=\\s*(?:[,;…?!.]|$)|\\s+(?:i|a|żeby|z|przed|po|w|na|do|od|oraz|dla|przez|jako)\\b)`,
  "giu",
);

function misAgreeingForms(
  value: string,
  key: string,
): Array<{ kind: string; form: string }> {
  const found: Array<{ kind: string; form: string }> = [];
  const taken = new Set<string>();
  const add = (kind: string, form: string) => {
    if (!taken.has(form)) {
      taken.add(form);
      found.push({ kind, form });
    }
  };
  // A screen names a place in its key without the sentence spelling the noun:
  // "Brak miejsc / Dodaj pierwszą…" lives under locationsPage.emptyDescription.
  const namesAPlace =
    /miejsc|\{\{location\}\}/i.test(value) ||
    /location|place|storage/i.test(key);
  if (namesAPlace) {
    for (const [kind, pattern] of [
      ["standing form", STANDING_FORM],
      ["genitive list", GENITIVE_LIST],
    ] as const) {
      for (const match of value.matchAll(pattern)) {
        add(kind, match[0]);
      }
    }
  }
  // A label stands for its referent whatever the key names, so it is swept
  // everywhere; the exception map is what says which referent is feminine.
  const label = value.trim();
  if (LABEL_VALUE.test(label)) {
    for (const match of label.matchAll(LABEL_WORD)) {
      add("status label", match[1]);
    }
  }
  // With the place's own name in the sentence nothing else feminine can own a
  // pronoun or a predicate; a sentence naming the place with the noun may
  // still talk about a feminine "liczba" or "ścieżka" of its own ("Zapisz ją
  // przed zamknięciem miejsca"), and there the pronoun is correct.
  if (/\{\{location\}\}/i.test(value)) {
    for (const [kind, pattern] of [
      ["feminine pronoun", FEMININE_PRONOUN],
      ["feminine predicate", FEMININE_PREDICATE],
    ] as const) {
      for (const match of value.matchAll(pattern)) {
        add(kind, match[0]);
      }
    }
  }
  return found;
}

/** Every mis-agreeing form under `node`, with the key that holds it. */
function agreementResidues(
  node: unknown,
  file: string,
  path: string[] = [],
): Array<{ file: string; key: string; form: string; value: string }> {
  const found: Array<{
    file: string;
    key: string;
    form: string;
    value: string;
  }> = [];
  const key = [file, ...path].join(" ");
  if (typeof node === "string") {
    for (const hit of misAgreeingForms(node, key)) {
      found.push({ file, key: path.join("."), form: hit.form, value: node });
    }
  } else if (Array.isArray(node)) {
    node.forEach((entry, index) => {
      found.push(...agreementResidues(entry, file, [...path, String(index)]));
    });
  } else if (node && typeof node === "object") {
    for (const [name, value] of Object.entries(node)) {
      found.push(...agreementResidues(value, file, [...path, name]));
    }
  }
  return found;
}

/**
 * Where a standing feminine form or a status label has a feminine noun of its
 * own, the sentence is right and the shape cannot see it. Named file-and-key
 * by file-and-key so the sweep stays strict everywhere else; a stale entry is
 * refused below. The noun named is the referent the call site renders.
 */
const AGREES_WITH_OWN_NOUN = new Map([
  [
    "modules/maker/i18n/pl.json bom.treeHint",
    "'pod inną' is the recipe the line is re-parented under",
  ],
  [
    "modules/warehouse/i18n/pl.json putaway.hints.location_order",
    "'do następnej' is the shelf the line passes on to",
  ],
  // status labels — each agrees with the noun its screen renders it for
  [
    "i18n/locales/pl/common.json settings.organization.memberRoleGroups.customBadge",
    "'Własna' is the grupa",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.fields.is_active",
    "'Aktywna' is the flaga",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.fields.is_default",
    "'Domyślna' is the flaga",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.values.ACTIVE",
    "'Aktywna' is the flaga",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.values.wms_session_paused",
    "'Wstrzymana' is the sesja skanowania",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.values.wms_session_completed",
    "'Zakończona' is the sesja skanowania",
  ],
  [
    "i18n/locales/pl/common.json settings.audit.values.wms_session_cancelled",
    "'Anulowana' is the sesja skanowania",
  ],
  [
    "i18n/locales/pl/common.json settings.rbac.builtInBadge",
    "'Wbudowana' is the rola",
  ],
  [
    "i18n/locales/pl/labels.json filters.statusPrinted",
    "'Wydrukowana' is the etykieta",
  ],
  [
    "i18n/locales/pl/labels.json filters.statusArchived",
    "'Zarchiwizowana' is the etykieta",
  ],
  ["i18n/locales/pl/labels.json filters.statusFree", "'Nowa' is the etykieta"],
  [
    "i18n/locales/pl/labels.json statusAssigned",
    "'Przypisana' is the etykieta",
  ],
  [
    "i18n/locales/pl/labels.json statusUnassigned",
    "'Nieprzypisana' is the etykieta",
  ],
  [
    "modules/equipment/i18n/pl.json table.warranty.active",
    "'Aktywna' is the gwarancja",
  ],
  [
    "modules/equipment/i18n/pl.json attestation.launched",
    "'Uruchomiona' is the atestacja",
  ],
  [
    "modules/equipment/i18n/pl.json attestation.status.ACTIVE",
    "'Aktywna' is the atestacja",
  ],
  [
    "modules/equipment/i18n/pl.json attestation.status.COMPLETED",
    "'Zamknięta' is the atestacja",
  ],
  [
    "modules/equipment/i18n/pl.json attestation.status.CANCELLED",
    "'Anulowana' is the atestacja",
  ],
  [
    "modules/inventory/i18n/pl.json lot.status.active",
    "'Aktywna' is the partia",
  ],
  [
    "modules/inventory/i18n/pl.json lot.status.held",
    "'Wstrzymana' is the partia",
  ],
  [
    "modules/inventory/i18n/pl.json lot.status.expired",
    "'Przeterminowana' is the partia",
  ],
  [
    "modules/inventory/i18n/pl.json lot.status.recalled",
    "'Wycofana' is the partia",
  ],
  [
    "modules/inventory/i18n/pl.json lots.setTo.expired",
    "'przeterminowaną' is the partia it marks",
  ],
  [
    "modules/inventory/i18n/pl.json lots.setTo.recalled",
    "'wycofaną' is the partia it marks",
  ],
  [
    "modules/maker/i18n/pl.json detail.setAsDefault",
    "'domyślną' is the receptura",
  ],
  ["modules/maker/i18n/pl.json pricing.saveDefault", "'domyślną' is the cena"],
  [
    "modules/recipes/i18n/pl.json picking.resumed_badge",
    "'Wznowiona' is the kompletacja",
  ],
  [
    "modules/recipes/i18n/pl.json ingredient_defaults.custom",
    "'Własna' is the wartość",
  ],
  [
    "modules/recipes/i18n/pl.json unit_conversions.custom",
    "'Własna' is the wartość",
  ],
  [
    "modules/recipes/i18n/pl.json import_export.review_unit_unrecognized_label",
    "'Nierozpoznana' is the jednostka",
  ],
  [
    "modules/stock_takes/i18n/pl.json started",
    "'Rozpoczęta' is the inwentaryzacja",
  ],
  [
    "modules/stock_takes/i18n/pl.json item.expected",
    "'Oczekiwana' is the ilość",
  ],
  ["modules/stock_takes/i18n/pl.json item.counted", "'Policzona' is the ilość"],
  [
    "modules/warehouse/i18n/pl.json detail.scanActiveLine",
    "'Następna' is the pozycja",
  ],
  [
    "modules/warehouse/i18n/pl.json detail.lineStatuses.DONE",
    "'Wykonana' is the linia",
  ],
  [
    "modules/warehouse/i18n/pl.json detail.lineStatuses.PARTIAL",
    "'Częściowa' is the linia",
  ],
  [
    "modules/warehouse/i18n/pl.json register.nextPage",
    "'Następna' is the strona",
  ],
  [
    "modules/warehouse/i18n/pl.json putaway.fields.active",
    "'Aktywna' is the reguła",
  ],
  [
    "modules/warehouse/i18n/pl.json putaway.status.active",
    "'Aktywna' is the reguła",
  ],
  [
    "modules/warehouse/i18n/pl.json putaway.status.inactive",
    "'Nieaktywna' is the reguła",
  ],
  [
    "modules/warehouse/i18n/pl.json packing.filling",
    "'Napełniana' is the paczka",
  ],
]);

describe("no Polish string keeps the gender of the retired noun", () => {
  const residues = () =>
    polishCatalogues().flatMap(([file, catalog]) =>
      agreementResidues(catalog, file),
    );

  it("agrees with miejsce in every catalogue", () => {
    const hits = residues()
      .filter((hit) => !AGREES_WITH_OWN_NOUN.has(`${hit.file} ${hit.key}`))
      .map((hit) => `${hit.file} :: ${hit.key} :: ${hit.form} :: ${hit.value}`);
    expect(hits).toEqual([]);
  });

  it("keeps every named exception on its toes", () => {
    const tripping = new Set(residues().map((hit) => `${hit.file} ${hit.key}`));
    for (const [name, reason] of AGREES_WITH_OWN_NOUN) {
      expect(tripping, `stale exception ${name} (${reason})`).toContain(name);
    }
  });

  it("would catch what the sweep corrected", () => {
    const forms = (value: string, key: string) =>
      misAgreeingForms(value, key).map((hit) => hit.form);
    expect(
      forms(
        "Utwórz pierwszy i kontynuuj bez opuszczania tego miejsca.",
        "required.description",
      ),
    ).toEqual(["pierwszy"]);
    expect(
      forms(
        "Dodaj pierwszą, żeby sprzęt miał gdzie stać.",
        "locationsPage.emptyDescription",
      ),
    ).toEqual(["pierwszą"]);
    expect(
      forms(
        "Zanieś towar do {{location}} i zeskanuj jej etykietę",
        "picking.destination_go_to",
      ),
    ).toEqual(["jej"]);
    expect(
      forms(
        "W {{location}} nic nie znaleziono. Potwierdzić ją jako policzoną i pustą?",
        "shelf.closeEmpty",
      ),
    ).toEqual(["policzoną", "pustą", "ją"]);
    expect(
      forms(
        "Potwierdzono, że {{location}} jest pusta.",
        "shelf.closedEmptyDone",
      ),
    ).toEqual(["{{location}} jest pusta"]);
    expect(
      forms(
        "Generuj i drukuj etykiety dla produktów i miejsca.",
        "modules.printing.description",
      ),
    ).toEqual(["produktów i miejsca"]);
    expect(forms("Pusta", "report.closedEmpty")).toEqual(["Pusta"]);
    expect(forms("Zamknięta przez: {{name}}", "shelf.closedBy")).toEqual([
      "Zamknięta",
    ]);
    expect(
      forms("Potwierdzona jako pusta przez: {{name}}", "shelf.closedEmptyBy"),
    ).toEqual(["Potwierdzona", "pusta"]);
    // The half-fix: the label itself agreed with the place, the "jako"
    // tail did not. That is how the residue survived two sweeps.
    expect(
      forms("Zamknięte jako pusta przez: {{name}}", "shelf.closedEmptyBy"),
    ).toEqual(["pusta"]);
    expect(forms("Oznacz jako przeterminowaną", "lots.setTo.expired")).toEqual([
      "przeterminowaną",
    ]);
  });

  it("and stays quiet where the noun is feminine or the agreement is right", () => {
    const forms = (value: string, key: string) =>
      misAgreeingForms(value, key).map((hit) => hit.form);
    // "półka" is feminine, "liczba" and "ścieżka" too, "pierwszy produkt" is
    // the product's own gender, and the corrected wording agrees with miejsce.
    expect(forms("Towar trafia na pierwszą półkę w tym miejscu.", "x")).toEqual(
      [],
    );
    expect(
      forms(
        "Jedna liczba w tym miejscu nie została zapisana. Zapisz ją przed zamknięciem miejsca.",
        "shelf.closeUnsaved_one",
      ),
    ).toEqual([]);
    expect(
      forms(
        "Miejsce można podać jako ścieżkę — tyle jej, ile trzeba.",
        "import.location_path_hint",
      ),
    ).toEqual([]);
    expect(
      forms(
        "Reguła pominięta — jej miejsce jest zarchiwizowane",
        "plannedWarning.archived",
      ),
    ).toEqual([]);
    expect(forms("Dodaj pierwszy produkt do jednego z miejsc", "x")).toEqual(
      [],
    );
    expect(
      forms(
        "Utwórz pierwsze i kontynuuj bez opuszczania tego miejsca.",
        "required.description",
      ),
    ).toEqual([]);
    expect(
      forms(
        "W {{location}} nic nie znaleziono. Potwierdzić je jako policzone i puste?",
        "shelf.closeEmpty",
      ),
    ).toEqual([]);
    expect(
      forms(
        "Potwierdzono, że {{location}} jest puste.",
        "shelf.closedEmptyDone",
      ),
    ).toEqual([]);
    expect(
      forms(
        "Generuj i drukuj etykiety dla produktów i miejsc.",
        "modules.printing.description",
      ),
    ).toEqual([]);
    // The corrected labels agree with miejsce, and a label that agrees with
    // its own feminine noun stays a reader's question, not a hit.
    expect(forms("Puste", "report.closedEmpty")).toEqual([]);
    expect(forms("Zamknięte przez: {{name}}", "shelf.closedBy")).toEqual([]);
    expect(
      forms("Potwierdzone jako puste przez: {{name}}", "shelf.closedEmptyBy"),
    ).toEqual([]);
    expect(forms("Zarchiwizowane", "archived.badge")).toEqual([]);
    expect(forms("Jednostka", "report.unit")).toEqual([]);
    expect(
      forms("Oznacz partię jako przeterminowaną", "lots.setTo.expired"),
    ).toEqual([]);
  });
});
