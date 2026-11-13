/**
 * source-text.mjs
 *
 * Shared text preparation for the gates that scan source as text.
 *
 * Most gates in this directory match shapes with regular expressions rather
 * than a parser, which means they see a mention of code and real code alike.
 * Blanking comments is the one correction all of them need, and it was
 * copied byte-for-byte into three of them before it lived here. One place
 * means one fix.
 *
 * What this deliberately does NOT do: blank string literals. It looks like
 * the obvious next step — a gate that reads `useStorages()` out of an error
 * message reports a call nobody makes — and it was measured and rejected.
 * Blanking a template literal also blanks its `${...}` holes, so a real call
 * inside `` `count: ${useStorages().length}` `` disappears. That trades a
 * false alarm for a false silence, which is the worse of the two: an alarm
 * argues with you, a silence agrees with you. A gate that needs to tell code
 * from prose needs a parser, not one more pass of blanking: the
 * query-error-read gate reads the TypeScript syntax tree for that.
 */

/**
 * Replace the contents of comments with spaces, keeping every newline.
 *
 * Line count and column offsets survive, so a finding's reported line number
 * is still the line the reader will open.
 *
 * Comment *openers* are recognised string-aware: a `/*` inside a string
 * literal (`accept="image/*"`) or a `//` inside a URL ("https://…") is code,
 * not prose, and blanking from there swallowed real code — a tag lost its
 * closing quote and a gate read the rest of the file as one attribute. The
 * contents of string literals are still not blanked (deliberate; see the
 * module docstring above), and a template hole (`${...}`) is code again, so
 * a comment inside one is still blanked.
 */
export function blankComments(text) {
  const chars = text.split("");
  const n = text.length;
  const blank = (i) => {
    if (chars[i] !== "\n") chars[i] = " ";
  };
  // Where we are: code, or inside a `'`/`"` string or a template literal.
  // A `${` inside a template opens a hole — code again, with its braces
  // counted until the matching `}` returns us to the template string.
  const stack = ["code"];
  let holeDepth = -1;
  let i = 0;
  while (i < n) {
    const ctx = stack[stack.length - 1];
    const c = text[i];
    if (ctx === "'" || ctx === '"' || (ctx === "tpl" && holeDepth === -1)) {
      if (c === "\\") {
        i += 2;
        continue;
      }
      if (ctx === "tpl") {
        if (c === "`") stack.pop();
        else if (c === "$" && text[i + 1] === "{") {
          holeDepth = 0;
          i += 2;
          continue;
        }
      } else if (c === ctx) {
        stack.pop();
      }
      i++;
      continue;
    }
    if (c === "'" || c === '"' || c === "`") {
      stack.push(c === "`" ? "tpl" : c);
      i++;
      continue;
    }
    if (c === "/" && text[i + 1] === "/") {
      while (i < n && text[i] !== "\n") blank(i++);
      continue;
    }
    if (c === "/" && text[i + 1] === "*") {
      blank(i++);
      blank(i++);
      while (i < n && !(text[i] === "*" && text[i + 1] === "/")) blank(i++);
      if (i < n) {
        blank(i++);
        blank(i++);
      }
      continue;
    }
    if (ctx === "tpl" && holeDepth >= 0) {
      if (c === "{") holeDepth++;
      else if (c === "}") holeDepth--;
    }
    i++;
  }
  return chars.join("");
}
