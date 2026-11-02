/**
 * Shared reading and parsing for the UI pattern detectors.
 *
 * Every detector answers the same question about the same corpus, so the walk
 * happens once and the parsed shapes (`<Button>` tags, className literals) are
 * cut here rather than re-derived with a slightly different regex in each
 * detector — that drift is exactly what let one gate guard an incident while
 * a review looked at the class.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

export const SRC = new URL("../../src/", import.meta.url).pathname;

let cached = null;
let cachedScripts = null;

/**
 * Every non-test file under `src/` whose name passes `keep`, read once.
 *
 * Done in Node rather than `grep -rl --include=*.tsx`, because the frontend
 * container carries BusyBox grep, which has no `--include` (GNU-only) — the
 * detectors must behave identically on the host and inside
 * `docker compose exec frontend`.
 */
function read(keep) {
  const out = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!entry.name.startsWith(".") && entry.name !== "node_modules")
          walk(full);
        continue;
      }
      if (!keep(entry.name)) continue;
      out.push({ path: relative(SRC, full), text: readFileSync(full, "utf8") });
    }
  };
  walk(SRC);

  return out.sort((a, b) => a.path.localeCompare(b.path));
}

/** Every non-test `.tsx` under `src/` — the corpus of rendered markup. */
export function sourceFiles() {
  cached ??= read(
    (name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx"),
  );
  return cached;
}

/**
 * The same corpus plus every non-test `.ts` — hooks and helpers included.
 *
 * A rule about what reaches the reader cannot stop at `.tsx`: half the
 * mistakes are made in a hook that hands a component a finished sentence.
 * Detectors that read markup stay on `sourceFiles`, so their counts keep
 * meaning what they meant.
 */
export function scriptFiles() {
  cachedScripts ??= read(
    (name) =>
      (name.endsWith(".ts") || name.endsWith(".tsx")) &&
      !name.endsWith(".test.ts") &&
      !name.endsWith(".test.tsx") &&
      !name.endsWith(".d.ts"),
  );
  return cachedScripts;
}

/** 1-indexed line number of an offset, for a `file:line` a terminal can open. */
export function lineAt(text, index) {
  return text.slice(0, index).split("\n").length;
}

/**
 * The same text with every block comment blanked out, newlines kept.
 *
 * A detector that reads raw text also reads the examples in the doc comments
 * explaining the rule — `label-line-box` reported the `<label>` in
 * `ListControlBar`'s own JSDoc, which is prose about the mistake and not the
 * mistake. Offsets and line numbers survive because the comment is replaced
 * character for character, so `lineAt` still points at the file the terminal
 * opens.
 *
 * Block comments only: `//` also lives inside every URL in the corpus, and a
 * rule that blanks the rest of those lines loses real code.
 */
export function withoutBlockComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (match) =>
    match.replace(/[^\n]/g, " "),
  );
}

/**
 * The offset of a tag's closing `>`, or -1 if it never closes.
 *
 * Not `[^>]*>`: a JSX attribute holds arbitrary expressions, and
 * `onClick={() => close()}` carries a `>` of its own. The cheap regex stops
 * at that arrow and reports a tag missing everything after it — including,
 * more often than not, the className the detector came to read. That blind
 * spot is why `<Button className="h-auto">` with an inline handler passed a
 * gate written to catch exactly it.
 */
export function tagEnd(text, start) {
  let depth = 0;
  let quote = null;

  for (let i = start; i < text.length; i++) {
    const ch = text[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}") depth--;
    else if (ch === ">" && depth === 0) return i;
  }
  return -1;
}

/** Opening tags of one component, with the offset each starts at. */
export function openingTags(text, component) {
  const out = [];

  for (const m of text.matchAll(new RegExp(`<${component}\\b`, "g"))) {
    const end = tagEnd(text, m.index);
    if (end === -1) continue;
    out.push({ tag: text.slice(m.index, end + 1), index: m.index });
  }
  return out;
}

/**
 * Opening tags of one component, each with the className of the element
 * directly enclosing it.
 *
 * A layout rule has to know the *parent*: `flex-1` stakes a button on the
 * axis of the container it is a flex item of, and one wrapper further out a
 * column container is no longer that. The nearest tag *before* the button in
 * the text is not the answer — it is a sibling, or a section that closed
 * pages ago. So the file is walked forward once over a stack of open
 * elements, the way a browser pairs tags; what the button sees as its parent
 * is whatever the stack holds when its own tag opens.
 *
 * The walk is a heuristic reader, not a parser, and stays total over text it
 * cannot read: a tag whose end never comes holds nothing open, a fragment
 * holds nothing at all, and a closing tag with no matching entry is ignored
 * rather than allowed to pop the stack inside out. `classNameOf` reads
 * plain-string classNames and `cn(...)` expressions alike, so a parent also
 * says whether its className was a literal — an expression's text is a
 * *maybe*, and a rule that must be sure gives up on it rather than guess.
 */
export function openingTagsWithParent(text, component) {
  const stack = [];
  const out = [];

  const tokens = [];
  for (const m of text.matchAll(/<[A-Za-z][A-Za-z0-9.]*/g))
    tokens.push({ at: m.index, closing: false, name: m[0].slice(1) });
  for (const m of text.matchAll(/<\/([A-Za-z][A-Za-z0-9.]*)/g))
    tokens.push({ at: m.index, closing: true, name: m[1] });
  tokens.sort((a, b) => a.at - b.at);

  const parentOf = () =>
    stack.length
      ? stack[stack.length - 1]
      : { className: null, literal: false };

  for (const { at, closing, name } of tokens) {
    if (closing) {
      for (let i = stack.length - 1; i >= 0; i--) {
        if (stack[i].name === name) {
          stack.length = i;
          break;
        }
      }
      continue;
    }

    const end = tagEnd(text, at);
    if (end === -1) continue;
    const tag = text.slice(at, end + 1);
    const selfClosing = tag.endsWith("/>");
    const className = classNameOf(tag);

    if (name === component) {
      const parent = parentOf();
      out.push({
        tag,
        index: at,
        parentClassName: parent.className,
        parentClassNameIsLiteral: parent.literal,
      });
    }
    if (!selfClosing)
      stack.push({
        name,
        className,
        literal: className !== null && classNameIsLiteral(tag),
      });
  }

  return out;
}

/**
 * The offset of the tag's own `className=`, or -1.
 *
 * Not `indexOf`: a prop can hold JSX of its own, and
 * `rightIcon={<button className="h-11 w-11">}` puts a className inside the tag
 * that belongs to a different element. A detector reading it judged the field
 * by its clear-search button — and every rule built on `classNameOf` inherited
 * that mistake.
 */
function ownClassNameAt(tag) {
  let depth = 0;
  let quote = null;

  for (let i = 0; i < tag.length; i++) {
    const ch = tag[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}") depth--;
    else if (depth === 0 && tag.startsWith("className=", i)) return i;
  }
  return -1;
}

/**
 * The classes a tag asks for — the inside of `className=`, whether it is a
 * plain string, a template literal or a `cn(...)` call with nested calls of
 * its own. Returns null when the tag sets no className.
 */
export function classNameOf(tag) {
  const at = ownClassNameAt(tag);
  if (at === -1) return null;

  const rest = tag.slice(at + "className=".length);

  if (rest.startsWith('"')) {
    const end = rest.indexOf('"', 1);
    return end === -1 ? null : rest.slice(1, end);
  }
  if (!rest.startsWith("{")) return null;

  let depth = 0;
  let quote = null;

  for (let i = 0; i < rest.length; i++) {
    const ch = rest[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return rest.slice(1, i);
  }
  return null;
}

/**
 * Whether a tag's own className is written as a plain string.
 *
 * `classNameOf` reads an expression too — rules like `button-size-override`
 * want the `cn(...)` text — but an expression's text is a *maybe*: only some
 * of its branches may hold a class, and which ones render is a judgement a
 * static read cannot make. A rule that must be sure the class is always
 * there asks this.
 */
export function classNameIsLiteral(tag) {
  const at = ownClassNameAt(tag);
  return at !== -1 && tag[at + "className=".length] === '"';
}

/**
 * The same text with comments blanked out — block comments and line comments
 * alike, newlines and offsets kept.
 *
 * `withoutBlockComments` is enough for a rule that reads JSX tags, because a
 * doc comment holding an example is a block. A rule that reads a *tag name*
 * needs this one instead: half of what a `<select>` scan finds in this repo is
 * a `//` line explaining why the previous `<select>` was removed.
 *
 * A `//` preceded by `:` is left alone — that is the middle of a URL, and
 * blanking the rest of that line takes real code with it.
 */
export function withoutComments(text) {
  return withoutBlockComments(text).replace(
    /(^|[^:])\/\/[^\n]*/g,
    (match, lead) => lead + " ".repeat(match.length - lead.length),
  );
}

/**
 * The `?` of the first ternary in an expression, and the `:` that answers it.
 *
 * Quote- and bracket-aware, so a `md:h-10` inside a string and an `a ? b : c`
 * inside a nested call are both read as what they are. `?.` and `??` are not
 * ternaries and are skipped.
 */
function firstTernary(expr) {
  let quote = null;
  let depth = 0;
  let start = -1;
  let pending = 0;

  for (let i = 0; i < expr.length; i++) {
    const ch = expr[i];

    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") quote = ch;
    else if ("({[".includes(ch)) depth++;
    else if (")}]".includes(ch)) depth--;
    else if (ch === "?") {
      if (expr[i + 1] === "." || expr[i + 1] === "?") i++;
      else if (start === -1) {
        start = i;
        depth = 0;
      } else pending++;
    } else if (ch === ":" && start !== -1 && depth === 0) {
      if (pending > 0) pending--;
      else return { question: start, colon: i };
    }
  }
  return null;
}

/** Hard stop: a className with several ternaries is not worth exploding. */
const MAX_ALTERNATIVES = 8;

/**
 * Every class list a className expression can actually produce.
 *
 * A rule that asks "does this button state its padding?" has to ask it of each
 * branch, not of the text of the whole expression. `className={variant ===
 * "bordered" ? "px-3 py-2.5 border" : "w-full"}` reads as padded when the two
 * branches are concatenated, and the second branch is the one that rendered a
 * 21px row.
 */
export function classNameAlternatives(className) {
  if (!className) return [""];

  const expand = (expr, out) => {
    if (out.length >= MAX_ALTERNATIVES) return;

    const found = firstTernary(expr);
    if (!found) {
      out.push(expr);
      return;
    }
    const head = expr.slice(0, findConditionStart(expr, found.question));
    const tail = expr.slice(found.colon + 1);
    // The condition itself holds no classes, so each alternative is the text
    // around the ternary plus one of its branches.
    expand(head + expr.slice(found.question + 1, found.colon) + tail, out);
    expand(head + tail, out);
  };

  const out = [];
  expand(className, out);
  return out;
}

/**
 * Where the condition of a ternary begins — back to the enclosing comma,
 * bracket or start of the expression. Everything from there to the `?` is a
 * test, never a class list.
 */
function findConditionStart(expr, question) {
  for (let i = question - 1; i >= 0; i--) {
    if (",({[".includes(expr[i])) return i + 1;
  }
  return 0;
}

/**
 * The part of a className that carries no responsive modifier.
 *
 * `cn()` is `twMerge`, which resolves conflicts within a variant group only:
 * a plain `h-8` displaces the variant's `h-11` but leaves its `md:h-10`
 * standing. So an override without a modifier wins below `md` and loses on
 * every desktop — silently, which is why review keeps passing it.
 */
export function withoutResponsive(className) {
  return className.replace(/\b[a-z]+:[^\s"'`]+/g, "");
}

/** The `size="…"` a tag asks for, or `"default"` when it asks for none. */
export function sizeOf(tag) {
  return tag.match(/size="([a-zA-Z]+)"/)?.[1] ?? "default";
}
