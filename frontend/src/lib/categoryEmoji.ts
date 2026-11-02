/**
 * Category emoji resolver and keyword map.
 *
 * The 4-layer cascade is the SINGLE SOURCE OF TRUTH for which emoji a
 * category renders with. The Python mirror in
 * ``backend/app/services/category_emoji.py`` must stay in sync with this
 * file (verified by ``test_keyword_maps_match_frontend``).
 *
 * Order within an entry: longer / more-specific keywords first so e.g.
 * 'ice cream' matches before 'cream' if both existed. Order across entries:
 * the matcher takes the FIRST entry whose keywords produce a match, so
 * place higher-priority concepts earlier.
 *
 * ``wholeWord: true`` enforces a word-boundary on BOTH sides (\\b{kw}\\b)
 * for known ambiguous stems (e.g. PL 'ser' must not match 'serwer').
 * False (default) uses only the start boundary (\\b{kw}), which is fine
 * for longer unambiguous stems.
 */

interface EmojiEntry {
  /** Lowercase keywords. First matching keyword wins. */
  keywords: string[];
  /** A single emoji glyph, e.g. "🥚". */
  emoji: string;
  /** When true, enforce \\b{kw}\\b (both sides). Default false. */
  wholeWord?: boolean;
}

export const KEYWORD_EMOJI_MAP: EmojiEntry[] = [
  // ── Food: meat & protein ─────────────────────────────────
  { keywords: ["beef", "wołowin"], emoji: "🥩" },
  { keywords: ["pork", "wieprzow"], emoji: "🐖" },
  { keywords: ["chicken", "kurczak"], emoji: "🍗" },
  { keywords: ["fish", "ryb"], emoji: "🐟" },
  { keywords: ["seafood", "shell", "krewet", "shrimp"], emoji: "🦐" },
  { keywords: ["egg", "jaj"], emoji: "🥚" },
  { keywords: ["meat", "mięso", "mieso"], emoji: "🍖" },
  // ── Food: prepared (soup/juice before produce so dish types win) ──
  { keywords: ["soup", "zupa"], emoji: "🍲" },
  { keywords: ["juice", "sok"], emoji: "🧃" },
  { keywords: ["ice cream", "lody"], emoji: "🍨" },
  // ── Food: bakery / pantry ────────────────────────────────
  { keywords: ["bread", "chleb"], emoji: "🍞" },
  { keywords: ["croissant", "rogalik"], emoji: "🥐" },
  { keywords: ["pizza"], emoji: "🍕" },
  { keywords: ["pasta", "makaron"], emoji: "🍝" },
  { keywords: ["rice", "ryż", "ryz"], emoji: "🍚" },
  { keywords: ["sandwich", "kanapk"], emoji: "🥪" },
  { keywords: ["salad", "sałatk"], emoji: "🥗" },
  { keywords: ["cookie", "ciastk"], emoji: "🍪" },
  { keywords: ["cake", "ciasto"], emoji: "🍰" },
  { keywords: ["candy", "cukierek"], emoji: "🍬" },
  { keywords: ["chocolate", "czekolad"], emoji: "🍫" },
  { keywords: ["honey", "miód", "miod"], emoji: "🍯" },
  { keywords: ["coffee", "kawa"], emoji: "☕" },
  { keywords: ["tea", "herbat"], emoji: "🍵" },
  { keywords: ["wine", "wino"], emoji: "🍷" },
  { keywords: ["beer", "piwo"], emoji: "🍺" },
  { keywords: ["water", "woda"], emoji: "💧" },
  // ── Food: dairy ──────────────────────────────────────────
  { keywords: ["milk", "mlek"], emoji: "🥛" },
  { keywords: ["cheese"], emoji: "🧀" },
  { keywords: ["ser"], emoji: "🧀", wholeWord: true }, // 'serwer' must NOT match
  { keywords: ["butter", "masł"], emoji: "🧈" },
  { keywords: ["yogurt", "jogurt"], emoji: "🥛" },
  // ── Food: produce ────────────────────────────────────────
  { keywords: ["vegetable", "warzywa"], emoji: "🥬" },
  { keywords: ["apple", "jabł"], emoji: "🍎" },
  { keywords: ["fruit", "owoc"], emoji: "🍎" },
  { keywords: ["banana", "banan"], emoji: "🍌" },
  { keywords: ["carrot", "marchew"], emoji: "🥕" },
  { keywords: ["tomato", "pomidor"], emoji: "🍅" },
  { keywords: ["potato", "ziemniak"], emoji: "🥔" },
  { keywords: ["onion", "cebula"], emoji: "🧅" },
  { keywords: ["garlic", "czosnek"], emoji: "🧄" },
  { keywords: ["corn", "kukurydz"], emoji: "🌽" },
  { keywords: ["mushroom", "pieczark"], emoji: "🍄" },
  { keywords: ["avocado", "awokado"], emoji: "🥑" },
  { keywords: ["lemon", "cytryna"], emoji: "🍋" },
  { keywords: ["grape", "winogron"], emoji: "🍇" },
  { keywords: ["cherry", "wiśnia"], emoji: "🍒" },
  { keywords: ["strawberry", "truskaw"], emoji: "🍓" },
  // ── Food: umbrella terms. A shop-level category is named "Dairy" or
  // "Snacks", not "Milk" — without these every such card fell through to
  // the last-resort box.
  { keywords: ["dairy", "nabiał", "nabial"], emoji: "🥛" },
  { keywords: ["frozen", "mrożon", "mrozon"], emoji: "🧊" },
  { keywords: ["deli"], emoji: "🥓", wholeWord: true }, // avoid 'delivery'
  { keywords: ["wędlin", "wedlin"], emoji: "🥓" },
  { keywords: ["drink", "beverage", "napój", "napoj"], emoji: "🥤" },
  { keywords: ["snack", "przekąsk", "przekask"], emoji: "🍿" },
  { keywords: ["sweet", "słodycz", "slodycz"], emoji: "🍬" },
  { keywords: ["spice", "przypraw", "herb", "zioł"], emoji: "🧂" },
  { keywords: ["sauce", "sos"], emoji: "🥫" },
  { keywords: ["oil", "olej", "oliw"], emoji: "🫒" },
  { keywords: ["flour", "mąka", "maka"], emoji: "🌾" },
  { keywords: ["grain", "kasza", "cereal", "płatk", "platk"], emoji: "🌾" },
  { keywords: ["produce", "warzyw"], emoji: "🥬" },
  // ── Equipment / IT (server before 'ser' handled above) ──
  { keywords: ["server", "serwer"], emoji: "🖥️" },
  { keywords: ["laptop", "notebook"], emoji: "💻" },
  { keywords: ["monitor", "ekran", "display"], emoji: "🖥️" },
  { keywords: ["phone", "smartphone", "telefon"], emoji: "📱" },
  { keywords: ["tablet"], emoji: "📱" },
  { keywords: ["keyboard", "klawiatur"], emoji: "⌨️" },
  { keywords: ["mouse", "mysz"], emoji: "🖱️" },
  { keywords: ["printer", "drukark"], emoji: "🖨️" },
  { keywords: ["camera", "aparat", "kamer"], emoji: "📷" },
  { keywords: ["cable", "kabel", "wire", "przewód"], emoji: "🔌" },
  { keywords: ["battery", "bateria", "akumulator"], emoji: "🔋" },
  { keywords: ["chip", "cpu", "procesor"], emoji: "🔩" },
  // ── Tools ────────────────────────────────────────────────
  { keywords: ["tool", "narzędz"], emoji: "🧰" },
  { keywords: ["hammer", "młotek"], emoji: "🔨" },
  { keywords: ["wrench", "klucz"], emoji: "🔧" },
  { keywords: ["screwdriver", "śrubokręt"], emoji: "🪛" },
  { keywords: ["drill", "wiertark"], emoji: "🪛" },
  { keywords: ["saw", "piła", "pila"], emoji: "🪚" },
  { keywords: ["knife", "nóż", "noz"], emoji: "🔪" },
  { keywords: ["scissors", "nożyce"], emoji: "✂️" },
  { keywords: ["ladder", "drabina"], emoji: "🪜" },
  // ── Containers / storage ─────────────────────────────────
  { keywords: ["box"], emoji: "📦", wholeWord: true }, // avoid 'boxer', 'boxes'
  { keywords: ["pudło", "pudel"], emoji: "📦" },
  { keywords: ["bottle", "butelk"], emoji: "🍼" },
  { keywords: ["jar", "słoik"], emoji: "🫙" },
  { keywords: ["canned", "canned food", "puszk"], emoji: "🥫" },
  { keywords: ["can"], emoji: "🥫", wholeWord: true }, // avoid 'canada', 'candle'
  { keywords: ["bag"], emoji: "🛍️", wholeWord: true }, // avoid 'bagel', 'baggage'
  { keywords: ["torba"], emoji: "🛍️" },
  // ── Office / stationery ──────────────────────────────────
  { keywords: ["book", "książka", "ksiazka"], emoji: "📚" },
  { keywords: ["notes"], emoji: "📓" },
  { keywords: ["pen"], emoji: "🖊️", wholeWord: true }, // avoid 'pencil', 'pending'
  { keywords: ["długopis"], emoji: "🖊️" },
  { keywords: ["pencil", "ołówek"], emoji: "✏️" },
  { keywords: ["paper", "papier"], emoji: "📄" },
  { keywords: ["folder", "teczk"], emoji: "📁" },
  { keywords: ["stapler", "zszywacz"], emoji: "📎" },
  // ── Medical / lab ────────────────────────────────────────
  { keywords: ["medicine", "lekarstw"], emoji: "💊" },
  { keywords: ["pill", "tabletka"], emoji: "💊" },
  { keywords: ["bandage", "bandaż"], emoji: "🩹" },
  { keywords: ["thermometer", "termometr"], emoji: "🌡️" },
  { keywords: ["syringe", "strzykawk"], emoji: "💉" },
  // ── Apparel / personal ───────────────────────────────────
  { keywords: ["shirt", "koszul"], emoji: "👕" },
  { keywords: ["shoe"], emoji: "👟", wholeWord: true }, // avoid 'shoebox'
  { keywords: ["but"], emoji: "👟" }, // PL 'but' (shoe)
  { keywords: ["glasses", "okular"], emoji: "👓" },
  { keywords: ["hat"], emoji: "🧢", wholeWord: true }, // avoid 'hatch', 'hatrack'
  { keywords: ["kapelusz", "czapk"], emoji: "🧢" },
  { keywords: ["glove", "rękawic"], emoji: "🧤" },
  // ── Vehicles ─────────────────────────────────────────────
  { keywords: ["car", "samochód"], emoji: "🚗" },
  { keywords: ["bike", "rower"], emoji: "🚲" },
  { keywords: ["truck", "ciężarów"], emoji: "🚚" },
  // ── Garden / outdoor ─────────────────────────────────────
  { keywords: ["plant", "roślin"], emoji: "🪴" },
  { keywords: ["flower", "kwiat"], emoji: "🌷" },
  { keywords: ["tree", "drzewo"], emoji: "🌳" },
  { keywords: ["seed", "nasion"], emoji: "🌱" },
  { keywords: ["fertilizer", "nawóz"], emoji: "🧪" },
];

/** Vertical default emoji (cascade layer 3). Keys correspond to
 *  ``Category.context_tag`` values actually used in the codebase. New
 *  verticals MUST add an entry here; the matcher also falls through to
 *  ``LAST_RESORT_EMOJI``. */
export const VERTICAL_DEFAULT_EMOJI: Record<string, string> = {
  equipment: "💻",
  food: "🥫",
};

export const LAST_RESORT_EMOJI = "📦";

/**
 * Resolve the display emoji for a category, applying the 4-layer cascade.
 *
 * Pure function — same inputs always yield the same output. Used by every
 * surface that renders a category avatar.
 */
export function resolveCategoryEmoji(input: {
  emoji?: string | null;
  name?: string | null;
  code?: string | null;
  contextTag?: string | null;
}): string {
  // Layer 1: explicit user override.
  if (input.emoji && input.emoji.trim().length > 0) {
    return input.emoji;
  }

  // Layer 2: keyword match on name OR code, case-insensitive, word-boundary.
  // \b keeps short keywords like "box" from matching inside "boxer"; the 'u'
  // flag makes \b Unicode-aware for PL diacritics. Entries with
  // wholeWord=true enforce BOTH boundaries (\b{kw}\b).
  const haystack = `${input.name ?? ""} ${input.code ?? ""}`.toLowerCase();
  for (const entry of KEYWORD_EMOJI_MAP) {
    const suffix = entry.wholeWord ? "\\b" : "";
    for (const kw of entry.keywords) {
      const re = new RegExp(`\\b${kw}${suffix}`, "u");
      if (re.test(haystack)) {
        return entry.emoji;
      }
    }
  }

  // Layer 3: vertical default.
  if (input.contextTag && VERTICAL_DEFAULT_EMOJI[input.contextTag]) {
    return VERTICAL_DEFAULT_EMOJI[input.contextTag];
  }

  // Layer 4: last resort.
  return LAST_RESORT_EMOJI;
}

/**
 * Return the full set of distinct emoji glyphs referenced anywhere in the
 * cascade. Used by the sync script to know which SVGs to download.
 */
export function collectReferencedEmojis(): string[] {
  const set = new Set<string>();
  for (const entry of KEYWORD_EMOJI_MAP) {
    set.add(entry.emoji);
  }
  for (const e of Object.values(VERTICAL_DEFAULT_EMOJI)) {
    set.add(e);
  }
  set.add(LAST_RESORT_EMOJI);
  return Array.from(set);
}
