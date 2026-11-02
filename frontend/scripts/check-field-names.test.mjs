/**
 * The scanner decides the verdict, so these pin the shapes it has to read.
 * Three of them are the false positives that broke earlier versions: a
 * `<select>` inside a docstring, an `id`/`htmlFor` pair written as separate
 * elements, and a prop value holding a `>`.
 */
import { describe, expect, it } from "vitest";

import {
  controlTags,
  diffBaseline,
  insideLabel,
  isScanned,
  labelledById,
  tally,
  unnamedIn,
} from "./check-field-names.mjs";

describe("controlTags", () => {
  it("reads a tag whose prop value contains a closing angle bracket", () => {
    const text = `<Input max={a > b ? a : b} label="x" />`;
    expect(controlTags(text, "Input")).toHaveLength(1);
    expect(controlTags(text, "Input")[0].tag).toContain('label="x"');
  });

  it("reads a multi-line tag", () => {
    const text = ["<Input", "  value={v}", '  label="x"', "/>"].join("\n");
    expect(controlTags(text, "Input")).toHaveLength(1);
  });

  it("does not mistake InputGroup for Input", () => {
    expect(controlTags("<InputGroup />", "Input")).toEqual([]);
  });
});

describe("comments are not code", () => {
  it("hides a control mentioned in a docstring", () => {
    // NativeSelect's own docstring talks about `<select>`; the first version
    // of this gate counted that sentence as an unnamed control.
    const text = "// the native `<select>` keeps the OS arrow\n";
    expect(unnamedIn("a.tsx", text)).toEqual([]);
  });
});

describe("unnamedIn", () => {
  it("accepts label", () => {
    expect(unnamedIn("a.tsx", '<Input label={t("x")} />')).toEqual([]);
  });

  it("accepts aria-label", () => {
    expect(unnamedIn("a.tsx", '<Input aria-label="x" />')).toEqual([]);
  });

  it("accepts a spread, whose contents cannot be read here", () => {
    expect(unnamedIn("a.tsx", "<Input {...field} />")).toEqual([]);
  });

  it("reports a control named only by its placeholder", () => {
    // A placeholder disappears on the first keystroke and may never be
    // announced — the defect this gate exists for.
    expect(unnamedIn("a.tsx", '<Input placeholder="Nazwa" />')).toEqual([
      { file: "a.tsx", line: 1, control: "Input" },
    ]);
  });

  it("reports each unnamed control in a file", () => {
    const text = '<Input />\n<Textarea />\n<Input label="x" />';
    expect(unnamedIn("a.tsx", text)).toHaveLength(2);
  });

  it("carries the line the control sits on", () => {
    const text = ["<div>", "  <Input />", "</div>"].join("\n");
    expect(unnamedIn("a.tsx", text)[0].line).toBe(2);
  });

  it("ignores a hidden input", () => {
    expect(unnamedIn("a.tsx", '<input type="hidden" value={v} />')).toEqual([]);
    expect(
      unnamedIn("a.tsx", '<input className="hidden" type="file" />'),
    ).toEqual([]);
  });

  it("skips a hidden file input whose accept holds a block-comment opener", () => {
    // `accept="image/*"`: the `/*` inside the string used to start a phantom
    // comment that swallowed the rest of the tag, so the `className="hidden"`
    // escape was never seen and the input was reported.
    const text = [
      "<input",
      "  ref={imageInputRef}",
      '  type="file"',
      '  accept="image/*"',
      '  className="hidden"',
      "  onChange={onImageUpload}",
      "/>",
      "{/* a later jsx comment */}",
    ].join("\n");
    expect(unnamedIn("a.tsx", text)).toEqual([]);
  });
});

describe("labelledById", () => {
  it("accepts an id wired to a htmlFor elsewhere in the file", () => {
    const text = "<label htmlFor={labelId}>x</label>\n<Input id={labelId} />";
    expect(unnamedIn("a.tsx", text)).toEqual([]);
    expect(labelledById("<Input id={labelId} />", text)).toBe(true);
  });

  it("accepts a quoted id the same way", () => {
    const text = '<label htmlFor="qty">x</label>\n<Input id="qty" />';
    expect(unnamedIn("a.tsx", text)).toEqual([]);
  });

  it("rejects an id nothing points at", () => {
    expect(labelledById('<Input id="qty" />', '<Input id="qty" />')).toBe(
      false,
    );
  });
});

describe("insideLabel", () => {
  it("accepts a control wrapped in a label element", () => {
    const text = '<label>\n  <input type="checkbox" />\n  Ślepy\n</label>';
    expect(unnamedIn("a.tsx", text)).toEqual([]);
  });

  it("does not carry the acceptance past the closing label", () => {
    const text = "<label><input /></label>\n<input />";
    expect(insideLabel(text, text.lastIndexOf("<input"))).toBe(false);
    expect(unnamedIn("a.tsx", text)).toHaveLength(1);
  });
});

describe("isScanned", () => {
  it("skips tests and non-tsx files", () => {
    expect(isScanned("a.test.tsx")).toBe(false);
    expect(isScanned("a.ts")).toBe(false);
    expect(isScanned("a.tsx")).toBe(true);
  });
});

describe("diffBaseline", () => {
  const f = (file, control = "Input") => ({ file, control, line: 1 });

  it("passes a finding the baseline already holds", () => {
    const { added } = diffBaseline([f("a.tsx")], { "a.tsx  <Input>": 1 });
    expect(added).toEqual([]);
  });

  it("fails a file the baseline never saw", () => {
    const { added } = diffBaseline([f("b.tsx")], { "a.tsx  <Input>": 1 });
    expect(added).toHaveLength(1);
    expect(added[0].key).toBe("b.tsx  <Input>");
  });

  it("fails a SECOND unnamed control in a file the baseline holds", () => {
    // Without this a baselined file becomes a free-for-all: the whole point
    // of the count beside the key.
    const { added } = diffBaseline([f("a.tsx"), f("a.tsx")], {
      "a.tsx  <Input>": 1,
    });
    expect(added).toEqual([{ key: "a.tsx  <Input>", was: 1, now: 2 }]);
  });

  it("reports a resolved baseline entry as fixed", () => {
    const { added, fixed } = diffBaseline([], { "a.tsx  <Input>": 1 });
    expect(added).toEqual([]);
    expect(fixed).toEqual([{ key: "a.tsx  <Input>", was: 1, now: 0 }]);
  });

  it("keys on file and control, not on the line", () => {
    expect([
      ...tally([f("a.tsx"), { ...f("a.tsx"), line: 99 }]).values(),
    ]).toEqual([2]);
  });
});
