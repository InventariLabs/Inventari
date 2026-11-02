/**
 * Words that open a numbered step or a tip, in every language the app ships.
 *
 * Deliberately not in the i18n catalogues, and deliberately not filtered by the
 * active language. This is parser input, not UI copy: the recipe was typed by
 * whoever wrote it, so a Polish user can perfectly well hold a German recipe,
 * and matching only the interface language would leave that text as one
 * undifferentiated block. Every list is matched, always.
 *
 * The plan asked for i18n resources here. Reading five catalogues to parse text
 * that has no relationship to the interface language would tie the parser to
 * i18n init for no gain — the deviation is on purpose.
 */
const STEP_PREFIXES = [
  "Krok", // pl
  "Step", // en
  "Schritt", // de
  "Étape", // fr
  "Etape", // fr, unaccented as commonly typed
  "Paso", // es
] as const;

const TIP_PREFIXES = [
  "Porada", // pl
  "Wskazówka", // pl
  "Tip", // en
  "Hint", // en
  "Tipp", // de
  "Conseil", // fr
  "Astuce", // fr
  "Consejo", // es
] as const;

/** `Krok 3:` / `Schritt 3.` — number, then a colon or a full stop. */
export const STEP_RE = new RegExp(
  `^(?:${STEP_PREFIXES.join("|")})\\s+(\\d+)\\s*[:.]\\s*(.*)$`,
  "i",
);

/** `Tip:` / `Conseil 2 :` — the number is optional, the separator is not. */
export const TIP_RE = new RegExp(
  `^(?:${TIP_PREFIXES.join("|")})\\s*\\d*\\s*[:.]\\s*(.*)$`,
  "i",
);
