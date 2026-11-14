/**
 * The helper decides what every text-scanning gate is allowed to see, so
 * these pin both halves of its contract: what it hides, and what it must
 * keep visible.
 */
import { describe, expect, it } from "vitest";

import { blankComments } from "./source-text.mjs";

describe("blankComments", () => {
  it("keeps the line count, so a finding's line number stays true", () => {
    const text = ["/* a", "   b */", "<input />"].join("\n");
    expect(blankComments(text).split("\n")).toHaveLength(3);
  });

  it("keeps column offsets, so a finding's column stays true", () => {
    const text = "const a = 1; // useStorages()\nconst b = 2;";
    expect(blankComments(text)).toHaveLength(text.length);
  });

  it("hides a line comment and a block comment", () => {
    expect(blankComments("// useStorages()").trim()).toBe("");
    expect(blankComments("/* useStorages() */").trim()).toBe("");
  });

  it("leaves string literals alone, on purpose", () => {
    // Blanking these would also blank the `${...}` holes of a template
    // literal and hide a real call inside one. Measured and rejected; see
    // the module docstring. If this test starts failing, read that first.
    const text = 'throw new Error("call useStorages() with a scope");';
    expect(blankComments(text)).toBe(text);
  });

  it("does not read /* inside a string literal as a comment opener", () => {
    // `accept="image/*"` on a hidden file input held a block-comment opener
    // inside a string; blanking from there to the next `*/` swallowed the
    // rest of the tag, and check-field-names then reported the hidden input
    // as an unnamed control (RecipeHeroCard). The real comment on
    // the next line is still blanked.
    const text = [
      '<input type="file" accept="image/*" className="hidden" />',
      "{/* a later jsx comment */}",
    ].join("\n");
    const blanked = blankComments(text);
    expect(blanked.split("\n")[0]).toBe(text.split("\n")[0]);
    expect(blanked.split("\n")[1]).not.toBe(text.split("\n")[1]);
    expect(blanked).toHaveLength(text.length);
  });

  it("does not read // inside a string literal as a line comment", () => {
    // The same family: a URL in a string used to lose everything from `//`
    // to the end of the line.
    const text = 'const url = "https://example.com/a";\nconst b = 2;';
    expect(blankComments(text)).toBe(text);
  });

  it("still blanks a real comment after a string, and inside a template hole", () => {
    const withComment = [
      'const url = "https://example.com/a"; // useStorages()',
      "const b = 2;",
    ].join("\n");
    expect(blankComments(withComment)).not.toBe(withComment);
    // A `${...}` hole is code again: a comment inside it is blanked. A `/*`
    // in the template's own text is a literal and stays.
    const inHole = "const s = `${ /* x */ useStorages().length } units`;";
    expect(blankComments(inHole)).toBe(inHole.replace("/* x */", "       "));
    const inTemplateText = "const s = `a /* x */ b`;";
    expect(blankComments(inTemplateText)).toBe(inTemplateText);
  });

  it("keeps blanking after a template nested in a template hole", () => {
    // The hole's brace depth used to be one variable shared by every
    // template, so the inner template's hole closed the outer one in the
    // wrong frame and every later comment was left as text.
    const nested = "const a = `${t(`x`)}`;\n{/* it is a comment */}\n";
    expect(blankComments(nested)).toBe(
      nested.replace("/* it is a comment */", " ".repeat(21)),
    );
    // The outer hole resumes after the inner template: braces and a comment
    // inside it are still read as code, and the text after it as a string.
    const resumes = "const a = `${f(`${g({ k: 1 })}`) /* c */} /* kept */`;\n// gone\n";
    expect(blankComments(resumes)).toBe(
      resumes.replace("/* c */", "       ").replace("// gone", "       "),
    );
  });
});
