#!/usr/bin/env node
/**
 * sync-fluent-emoji.mjs — Fetch Fluent UI Emoji SVGs for the keyword map.
 *
 * We self-host a subset of Fluent UI Emoji so the rendered category avatar is identical on every OS.
 *
 * Usage:
 *   node scripts/sync-fluent-emoji.mjs --sync   # download missing SVGs + regen manifest
 *   node scripts/sync-fluent-emoji.mjs --check  # CI guard: fail if any SVG missing
 *
 * Source: microsoft/fluentui-emoji (MIT).
 *   https://github.com/microsoft/fluentui-emoji/tree/main/assets
 *
 * Output:
 *   frontend/public/emoji/<codepoint>.svg   ~3 KB each
 *   frontend/src/lib/fluent-emoji-manifest.ts   emoji -> '/emoji/<codepoint>.svg'
 *
 * The .ts file `frontend/src/lib/categoryEmoji.ts` is the single source of
 * truth for the keyword map. This script regex-parses it to find every
 * distinct emoji literal in `KEYWORD_EMOJI_MAP`, `VERTICAL_DEFAULT_EMOJI`,
 * and `LAST_RESORT_EMOJI`. Emojis not in the manifest render as native
 * font emoji (graceful fallback handled by `<FluentEmoji>`).
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..");
const keywordMapTs = join(repoRoot, "src", "lib", "categoryEmoji.ts");
const publicEmojiDir = join(repoRoot, "public", "emoji");
const manifestTs = join(repoRoot, "src", "lib", "fluent-emoji-manifest.ts");

const FLUENT_REPO = "microsoft/fluentui-emoji";
const FLUENT_BRANCH = "main";

// Fluent UI Emoji uses English CLDR directory names (e.g. ``Avocado``,
// ``Egg``) inside ``assets/``. The CLDR name is **not** the same as the
// Unicode codepoint. The mapping below is hand-curated for the emojis
// referenced by ``categoryEmoji.ts``; the sync script uses it to build
// the correct upstream URL.
//
// When adding a new emoji to the keyword map, also add its CLDR name here.
// The CLDR name is found in each asset's ``metadata.json`` (e.g. for 🥚:
//   https://github.com/microsoft/fluentui-emoji/tree/main/assets/Egg).
const EMOJI_TO_CLDR = {
  "🥚": "Egg",
  "🥩": "Cut of meat",
  "🥓": "Bacon",
  "🐖": "Pig",
  "🍗": "Poultry leg",
  "🐟": "Fish",
  "🦐": "Shrimp",
  "🍖": "Meat on bone",
  "🍲": "Pot of food",
  "🧃": "Beverage box",
  "🍨": "Ice cream",
  "🍞": "Bread",
  "🥐": "Croissant",
  "🍕": "Pizza",
  "🍝": "Spaghetti",
  "🍚": "Cooked rice",
  "🥪": "Sandwich",
  "🥗": "Green salad",
  "🍪": "Cookie",
  "🍰": "Shortcake",
  "🍬": "Candy",
  "🍫": "Chocolate bar",
  "🍯": "Honey pot",
  "☕": "Hot beverage",
  "🍵": "Teacup without handle",
  "🍷": "Wine glass",
  "🍺": "Beer mug",
  "💧": "Droplet",
  "🥛": "Glass of milk",
  "🧊": "Ice",
  "🥤": "Cup with straw",
  "🍿": "Popcorn",
  "🧂": "Salt",
  "🫒": "Olive",
  "🌾": "Sheaf of rice",
  "🧀": "Cheese wedge",
  "🧈": "Butter",
  "🥬": "Leafy green",
  "🍎": "Red apple",
  "🍌": "Banana",
  "🥕": "Carrot",
  "🍅": "Tomato",
  "🥔": "Potato",
  "🧅": "Onion",
  "🧄": "Garlic",
  "🌽": "Ear of corn",
  "🍄": "Mushroom",
  "🥑": "Avocado",
  "🍋": "Lemon",
  "🍇": "Grapes",
  "🍒": "Cherries",
  "🍓": "Strawberry",
  "💻": "Laptop",
  "🖥️": "Desktop computer",
  "📺": "Television",
  "📱": "Mobile phone",
  "⌨️": "Keyboard",
  "🖱️": "Computer mouse",
  "🖨️": "Printer",
  "📷": "Camera",
  "🔌": "Electric plug",
  "🔋": "Battery",
  "🔩": "Nut and bolt",
  "🧰": "Toolbox",
  "🔨": "Hammer",
  "🔧": "Wrench",
  "🪛": "Screwdriver",
  "🪚": "Carpentry saw",
  "🔪": "Kitchen knife",
  "🪜": "Ladder",
  "📦": "Package",
  "🍼": "Baby bottle",
  "🫙": "Jar",
  "🥫": "Canned food",
  "🛍️": "Shopping bags",
  "📚": "Books",
  "📓": "Notebook",
  "🖊️": "Pen",
  "✏️": "Pencil",
  "📄": "Page facing up",
  "📁": "File folder",
  "📎": "Paperclip",
  "💊": "Pill",
  "🩹": "Adhesive bandage",
  "🌡️": "Thermometer",
  "💉": "Syringe",
  "👕": "T-shirt",
  "👟": "Running shoe",
  "👓": "Glasses",
  "🧢": "Billed cap",
  "🧤": "Gloves",
  "🚗": "Automobile",
  "🚲": "Bicycle",
  "🚚": "Delivery truck",
  "🪴": "Potted plant",
  "🌷": "Tulip",
  "🌳": "Deciduous tree",
  "🌱": "Seedling",
  "🧪": "Test tube",
  "📁": "File folder",
};

// ── Argument parsing ──────────────────────────────────────────────────────
const args = new Set(process.argv.slice(2));
const mode = args.has("--check") ? "check" : "sync";

// ── 1. Collect emoji literals from the keyword-map TS file ────────────────
function collectEmojisFromTs() {
  const src = readFileSync(keywordMapTs, "utf8");
  // Match emoji literals: '🥚' or "🥚" (single character inside quotes).
  // We restrict to single-glyph strings to avoid false positives on
  // multi-character 'ice cream' style keywords.
  const emojiRe =
    /['"]([\p{Emoji_Presentation}\p{Extended_Pictographic}])['"]/gu;
  const set = new Set();
  for (const m of src.matchAll(emojiRe)) {
    set.add(m[1]);
  }
  return Array.from(set);
}

// ── 2. Reserved: was toCodepointHex; not used after CLDR-based mapping ────

// ── 3. Download a single SVG from the upstream repo ───────────────────────
async function fetchSvg(emoji) {
  const cldr = EMOJI_TO_CLDR[emoji];
  if (!cldr) {
    throw new Error(
      `No CLDR mapping for ${emoji}. Add it to EMOJI_TO_CLDR in sync-fluent-emoji.mjs.`,
    );
  }
  // Upstream layout: <cldr>/Color/<cldr_lowercase>_color.svg
  const slug = cldr.toLowerCase().replace(/\s+/g, "_");
  const url = `https://raw.githubusercontent.com/${FLUENT_REPO}/${FLUENT_BRANCH}/assets/${encodeURIComponent(cldr)}/Color/${slug}_color.svg`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }
  return res.text();
}

// ── 4. Write the manifest TS file ─────────────────────────────────────────
function writeManifest(emojis) {
  const entries = emojis
    .map((e) => {
      const cldr = EMOJI_TO_CLDR[e];
      if (!cldr) return null; // skip unmapped
      const slug = cldr.toLowerCase().replace(/\s+/g, "_");
      return `  ${JSON.stringify(e)}: ${JSON.stringify("/emoji/" + slug + "_color.svg")},`;
    })
    .filter((x) => x !== null);
  const content =
    `// AUTO-GENERATED by scripts/sync-fluent-emoji.mjs — do not edit by hand.\n` +
    `// Re-run \`npm run sync:emoji\` after editing the keyword map.\n` +
    `// Glyphs not listed here fall back to native font emoji (see <FluentEmoji>).\n` +
    `\n` +
    `export const FluentEmojiManifest: Record<string, string> = {\n` +
    entries.join("\n") +
    `\n};\n`;
  writeFileSync(manifestTs, content, "utf8");
}

// ── 5. Main flow ─────────────────────────────────────────────────────────
async function main() {
  if (!existsSync(keywordMapTs)) {
    console.error(`[sync-fluent-emoji] Cannot find ${keywordMapTs}`);
    process.exit(1);
  }
  const emojis = collectEmojisFromTs();
  console.log(
    `[sync-fluent-emoji] Found ${emojis.length} distinct emoji in keyword map.`,
  );

  if (mode === "check") {
    // CI guard: ensure every emoji has a local SVG.
    let missing = 0;
    for (const e of emojis) {
      const cldr = EMOJI_TO_CLDR[e];
      if (!cldr) {
        console.error(`  MISSING MAPPING: ${e} — no CLDR entry`);
        missing += 1;
        continue;
      }
      const slug = cldr.toLowerCase().replace(/\s+/g, "_");
      const path = join(publicEmojiDir, `${slug}_color.svg`);
      if (!existsSync(path)) {
        console.error(`  MISSING: ${e} -> ${path}`);
        missing += 1;
      }
    }
    if (missing > 0) {
      console.error(
        `[sync-fluent-emoji] ${missing} emoji SVG(s) missing. ` +
          `Run \`npm run sync:emoji\` to fetch them.`,
      );
      process.exit(1);
    }
    console.log("[sync-fluent-emoji] All SVGs present. OK.");
    return;
  }

  // mode === 'sync'
  if (!existsSync(publicEmojiDir)) {
    mkdirSync(publicEmojiDir, { recursive: true });
  }
  let downloaded = 0;
  let skipped = 0;
  let failed = 0;
  for (const e of emojis) {
    const cldr = EMOJI_TO_CLDR[e];
    if (!cldr) {
      failed += 1;
      console.error(
        `  FAILED: ${e} — no CLDR mapping. Add it to EMOJI_TO_CLDR.`,
      );
      continue;
    }
    const slug = cldr.toLowerCase().replace(/\s+/g, "_");
    const path = join(publicEmojiDir, `${slug}_color.svg`);
    if (existsSync(path)) {
      skipped += 1;
      continue;
    }
    try {
      const svg = await fetchSvg(e);
      writeFileSync(path, svg, "utf8");
      downloaded += 1;
      process.stdout.write(`  downloaded ${e} (${slug}_color.svg)\n`);
    } catch (err) {
      failed += 1;
      console.error(`  FAILED: ${e} (${slug}_color.svg) — ${err.message}`);
    }
  }
  writeManifest(emojis);
  console.log(
    `[sync-fluent-emoji] Done. downloaded=${downloaded} skipped=${skipped} failed=${failed}. ` +
      `Manifest written to ${manifestTs}.`,
  );
  if (failed > 0) process.exit(1);
}

main().catch((err) => {
  console.error("[sync-fluent-emoji] Unexpected error:", err);
  process.exit(1);
});
