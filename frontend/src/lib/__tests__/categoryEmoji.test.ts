import { describe, it, expect } from "vitest";
import {
  KEYWORD_EMOJI_MAP,
  LAST_RESORT_EMOJI,
  VERTICAL_DEFAULT_EMOJI,
  collectReferencedEmojis,
  resolveCategoryEmoji,
} from "@/lib/categoryEmoji";

// ── Equipment presets each get a glyph of their own ─────────────────────

describe("resolveCategoryEmoji — the equipment presets", () => {
  it.each([
    ["Desktop Computer", "🖥️"],
    ["Network Device", "🔌"],
    ["Peripheral", "🖱️"],
  ])(
    "gives %s a glyph of its own instead of the last-resort box",
    (name, emoji) => {
      const resolved = resolveCategoryEmoji({ name, contextTag: "equipment" });
      expect(resolved).toBe(emoji);
      expect(resolved).not.toBe(LAST_RESORT_EMOJI);
    },
  );
});

// ── Layer 1: user override wins ─────────────────────────────────────────

describe("resolveCategoryEmoji — Layer 1: user override", () => {
  it("explicit emoji beats keyword match", () => {
    // "Eggs" would match 'egg' → 🥚 via Layer 2, but explicit emoji wins.
    expect(resolveCategoryEmoji({ emoji: "🐔", name: "Eggs" })).toBe("🐔");
  });

  it("explicit emoji beats vertical default", () => {
    expect(
      resolveCategoryEmoji({
        emoji: "🎨",
        name: "Generic",
        contextTag: "equipment",
      }),
    ).toBe("🎨");
  });

  it("explicit emoji beats last resort", () => {
    expect(resolveCategoryEmoji({ emoji: "⭐", name: "", code: "" })).toBe(
      "⭐",
    );
  });

  it("whitespace-only emoji is treated as no override", () => {
    expect(resolveCategoryEmoji({ emoji: "   ", name: "Eggs" })).toBe("🥚");
  });

  it("null emoji is treated as no override", () => {
    expect(resolveCategoryEmoji({ emoji: null, name: "Eggs" })).toBe("🥚");
  });
});

// ── Layer 2: keyword match ──────────────────────────────────────────────

describe("resolveCategoryEmoji — Layer 2: keyword match", () => {
  it.each([
    // Food: meat & protein
    ["Beef stew", "🥩"],
    ["Wołowina mielona", "🥩"],
    ["Pork chops", "🐖"],
    ["Chicken breast", "🍗"],
    ["Kurczak cały", "🍗"],
    ["Fresh fish", "🐟"],
    ["Ryba z frytownicy", "🐟"],
    ["Shrimp cocktail", "🦐"],
    ["Krewetki mrożone", "🦐"],
    ["Eggs (12)", "🥚"],
    ["Jajka wiejskie", "🥚"],
    ["Meat balls", "🍖"],
    ["Mięso mielone", "🍖"],
    // Prepared (dish types win)
    ["Soup of the day", "🍲"],
    ["Zupa pomidorowa", "🍲"],
    ["Salad niçoise", "🥗"],
    ["Sałatka grecka", "🥗"],
    ["Orange juice", "🧃"],
    ["Sok jabłkowy", "🧃"],
    ["Ice cream", "🍨"],
    ["Lody waniliowe", "🍨"],
    // Bakery / pantry
    ["Bread loaf", "🍞"],
    ["Chleb wiejski", "🍞"],
    ["Pizza Margherita", "🍕"],
    ["Pasta carbonara", "🍝"],
    ["Makaron spaghetti", "🍝"],
    ["Rice bowl", "🍚"],
    ["Ryż basmati", "🍚"],
    ["Coffee beans", "☕"],
    ["Kawa mielona", "☕"],
    ["Tea time", "🍵"],
    ["Herbata czarna", "🍵"],
    ["Wine cellar", "🍷"],
    ["Wino czerwone", "🍷"],
    ["Beer craft", "🍺"],
    ["Piwo pszeniczne", "🍺"],
    ["Water bottle", "💧"],
    ["Woda mineralna", "💧"],
    // Dairy
    ["Milk 2%", "🥛"],
    ["Mleko UHT", "🥛"],
    ["Cheese board", "🧀"],
    ["Ser żółty", "🧀"],
    ["Butter unsalted", "🧈"],
    ["Masło ekstra", "🧈"],
    ["Greek yogurt", "🥛"],
    // Produce
    ["Fresh vegetable mix", "🥬"],
    ["Warzywa na patelnię", "🥬"],
    ["Apple pie", "🍎"],
    ["Jabłka zielone", "🍎"],
    ["Banana split", "🍌"],
    ["Banan dojrzały", "🍌"],
    ["Carrot sticks", "🥕"],
    ["Marchewka", "🥕"],
    ["Tomato sauce", "🍅"],
    ["Pomidory malinowe", "🍅"],
    ["Potato wedges", "🥔"],
    ["Ziemniaki młode", "🥔"],
    ["Onion rings", "🧅"],
    ["Cebula czerwona", "🧅"],
    // Equipment
    ["Laptop bag", "💻"],
    ["Monitor stand", "🖥️"],
    ["Ekran LCD", "🖥️"],
    ["Phone case", "📱"],
    ["Smartphone Pro", "📱"],
    ["Telefon biurowy", "📱"],
    ["Keyboard wireless", "⌨️"],
    ["Klawiatura mechaniczna", "⌨️"],
    ["Mouse pad", "🖱️"],
    ["Mysz bezprzewodowa", "🖱️"],
    ["Printer ink", "🖨️"],
    ["Drukarka laserowa", "🖨️"],
    ["Server rack", "🖥️"],
    ["Serwer produkcyjny", "🖥️"],
    ["Cable HDMI", "🔌"],
    ["Kabel sieciowy", "🔌"],
    // Tools
    ["Hammer drill", "🔨"],
    ["Młotek ślusarski", "🔨"],
    ["Wrench set", "🔧"],
    ["Klucz płaski", "🔧"],
    // Containers
    ["Glass bottle", "🍼"],
    ["Butelka wina", "🍼"],
    ["Storage jar", "🫙"],
    ["Słoik na przetwory", "🫙"],
    ["Canned beans", "🥫"],
    ["Puszka tuńczyka", "🥫"],
    // Office
    ["Office paper", "📄"],
    ["Papier ksero", "📄"],
    ["Długopis żelowy", "🖊️"],
    // Medical
    ["Pain medicine", "💊"],
    ["Lekarstwa domowe", "💊"],
    // Vehicles
    ["Family car", "🚗"],
    ["Samochód służbowy", "🚗"],
    ["Mountain bike", "🚲"],
    ["Rower górski", "🚲"],
  ])('"%s" resolves to %s', (name, expected) => {
    expect(resolveCategoryEmoji({ name })).toBe(expected);
  });

  it("matches on code when name is empty", () => {
    expect(resolveCategoryEmoji({ name: "", code: "EGGS" })).toBe("🥚");
  });

  it("tells the seeded Pork and Cold cuts apart", () => {
    // Both rendered the bacon, side by side in one freezer group.
    expect(resolveCategoryEmoji({ name: "Pork", code: "pork" })).not.toBe(
      resolveCategoryEmoji({ name: "Cold cuts", code: "deli" }),
    );
  });

  it("is case-insensitive", () => {
    expect(resolveCategoryEmoji({ name: "eggs" })).toBe("🥚");
    expect(resolveCategoryEmoji({ name: "EGGS" })).toBe("🥚");
    expect(resolveCategoryEmoji({ name: "EgGs" })).toBe("🥚");
  });
});

// ── Layer 3: vertical default ────────────────────────────────────────────

describe("resolveCategoryEmoji — Layer 3: vertical default", () => {
  it("equipment context with no keyword match", () => {
    expect(
      resolveCategoryEmoji({ name: "Xylophone", contextTag: "equipment" }),
    ).toBe("💻");
  });

  it("food context with no keyword match", () => {
    expect(
      resolveCategoryEmoji({ name: "Xylophone", contextTag: "food" }),
    ).toBe("🥫");
  });

  it("keyword beats vertical default", () => {
    expect(
      resolveCategoryEmoji({ name: "Milk 2%", contextTag: "equipment" }),
    ).toBe("🥛");
  });

  it("unknown context_tag falls through to last resort", () => {
    expect(
      resolveCategoryEmoji({
        name: "Xylophone",
        contextTag: "unknown_vertical",
      }),
    ).toBe(LAST_RESORT_EMOJI);
  });

  it("null context_tag falls through to last resort", () => {
    expect(resolveCategoryEmoji({ name: "Xylophone", contextTag: null })).toBe(
      LAST_RESORT_EMOJI,
    );
  });
});

// ── Layer 4: last resort ────────────────────────────────────────────────

describe("resolveCategoryEmoji — Layer 4: last resort", () => {
  it("returns package when everything is empty", () => {
    expect(
      resolveCategoryEmoji({
        emoji: null,
        name: "",
        code: "",
        contextTag: null,
      }),
    ).toBe(LAST_RESORT_EMOJI);
  });

  it("returns package when everything is null", () => {
    expect(
      resolveCategoryEmoji({
        emoji: null,
        name: null,
        code: null,
        contextTag: null,
      }),
    ).toBe(LAST_RESORT_EMOJI);
  });

  it("returns package for unmatched name with no context", () => {
    expect(resolveCategoryEmoji({ name: "Zzzqwertyuiop", code: "" })).toBe(
      LAST_RESORT_EMOJI,
    );
  });
});

// ── Word-boundary rule (critical) ────────────────────────────────────────

describe("resolveCategoryEmoji — word-boundary safety", () => {
  it("PL 'ser' does not match 'serwer' (server)", () => {
    expect(resolveCategoryEmoji({ name: "Serwer produkcyjny" })).toBe("🖥️");
  });

  it("'ser' matches as a whole word", () => {
    expect(resolveCategoryEmoji({ name: "Ser żółty" })).toBe("🧀");
    expect(resolveCategoryEmoji({ name: "Ser" })).toBe("🧀");
  });

  it("'can' does not match 'Canada'", () => {
    expect(resolveCategoryEmoji({ name: "Canada" })).toBe(LAST_RESORT_EMOJI);
  });

  it("'can' does not match 'Candle'", () => {
    expect(resolveCategoryEmoji({ name: "Candle wax" })).toBe(
      LAST_RESORT_EMOJI,
    );
  });

  it("'canned' still matches (separate prefix-keyword)", () => {
    expect(resolveCategoryEmoji({ name: "Canned beans" })).toBe("🥫");
  });

  it("'can' matches as a whole word", () => {
    expect(resolveCategoryEmoji({ name: "Can of beans" })).toBe("🥫");
  });

  it("'box' does not match 'Boxer'", () => {
    expect(resolveCategoryEmoji({ name: "Boxer" })).toBe(LAST_RESORT_EMOJI);
  });

  it("'box' matches as a whole word", () => {
    expect(resolveCategoryEmoji({ name: "Storage box" })).toBe("📦");
    expect(resolveCategoryEmoji({ name: "Box" })).toBe("📦");
  });

  it("'box' code matches", () => {
    expect(resolveCategoryEmoji({ name: "", code: "BOX-A1" })).toBe("📦");
  });

  it("'bag' does not match 'Bagel'", () => {
    expect(resolveCategoryEmoji({ name: "Bagel breakfast" })).toBe(
      LAST_RESORT_EMOJI,
    );
  });

  it("'hat' does not match 'Hatch'", () => {
    expect(resolveCategoryEmoji({ name: "Hatch door" })).toBe(
      LAST_RESORT_EMOJI,
    );
  });

  it("'ice cream' phrase matches", () => {
    expect(resolveCategoryEmoji({ name: "Ice cream tub" })).toBe("🍨");
  });

  it("Unicode word boundary works for Polish diacritics", () => {
    expect(resolveCategoryEmoji({ name: "Cebula czerwona" })).toBe("🧅");
  });
});

// ── Constants & helpers ────────────────────────────────────────────────

describe("constants & helpers", () => {
  it("last resort is package", () => {
    expect(LAST_RESORT_EMOJI).toBe("📦");
  });

  it("vertical defaults contain equipment and food", () => {
    expect(VERTICAL_DEFAULT_EMOJI.equipment).toBe("💻");
    expect(VERTICAL_DEFAULT_EMOJI.food).toBe("🥫");
  });

  it("map is non-empty", () => {
    expect(KEYWORD_EMOJI_MAP.length).toBeGreaterThan(0);
  });

  it("glyph diversity is healthy (≥20 distinct glyphs)", () => {
    const glyphs = new Set(KEYWORD_EMOJI_MAP.map((e) => e.emoji));
    expect(glyphs.size).toBeGreaterThanOrEqual(20);
  });

  it("collectReferencedEmojis returns every distinct glyph", () => {
    const collected = new Set(collectReferencedEmojis());
    // Should include at least one of each entry, vertical defaults, and last resort
    expect(collected.has(LAST_RESORT_EMOJI)).toBe(true);
    expect(collected.has(VERTICAL_DEFAULT_EMOJI.equipment)).toBe(true);
    expect(collected.has(VERTICAL_DEFAULT_EMOJI.food)).toBe(true);
    // Should be a deduped list (no duplicates)
    expect(collected.size).toBe(collectReferencedEmojis().length);
  });
});
