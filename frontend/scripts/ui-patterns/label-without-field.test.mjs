import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import labelWithoutField from "./label-without-field.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("label-without-field", () => {
  it("reports a label written above a field it does not point at", () => {
    const { findings } = labelWithoutField.run(
      files(`<div>
        <label className="block text-sm">Name</label>
        <Input value={name} onChange={onChange} />
      </div>`),
    );

    // One mistake, two anchors: the label names nothing, and the input —
    // no `label` prop, no id to point at — has no name either. Any correct
    // fix (the `label` prop, or `htmlFor` + `id`) clears both.
    expect(findings).toEqual(["Fixture.tsx:2", "Fixture.tsx:3"]);
  });

  it("leaves a label that points at its field", () => {
    const { findings } = labelWithoutField.run(
      files(`<label htmlFor="site">Site</label>
      <NativeSelect id="site" />`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a label wrapped around its control", () => {
    const { findings } = labelWithoutField.run(
      files(`<label className="inline-flex">
        <input type="checkbox" checked={on} />
        <span>Generate labels</span>
      </label>`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read the prose explaining the mistake as the mistake", () => {
    const { findings } = labelWithoutField.run(
      files(`// A hand-rolled <label> above the field is what this replaced.
      /* <label>Name</label> is what it used to be. */
      <Input label="Name" />`),
    );

    expect(findings).toEqual([]);
  });
});

/**
 * The module the class was drained in stays at zero.
 *
 * Roughly twenty dialogs in equipment wrote `<label>` above a field with
 * neither `htmlFor` nor the control inside it. The rule is not blocking yet —
 * the rest of the app still has findings — so this is what keeps them from
 * coming back here.
 */
const EQUIPMENT_ROOT = join(process.cwd(), "src", "modules", "equipment");

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__") continue;
      out.push(...walk(full));
      continue;
    }
    if (entry.endsWith(".tsx")) out.push(full);
  }
  return out;
}

describe("labels in the equipment module", () => {
  it("point at their field or wrap it", () => {
    const sources = walk(EQUIPMENT_ROOT).map((path) => ({
      path: relative(EQUIPMENT_ROOT, path),
      text: readFileSync(path, "utf8"),
    }));

    expect(labelWithoutField.run(sources).findings).toEqual([]);
  });
});

describe("a control with no label at all", () => {
  it("reports a hand-rolled control in a file that holds no <label>", () => {
    const { findings } = labelWithoutField.run(
      files(`<div>
        <span className="text-xs">Target margin</span>
        <input type="range" min={0} max={95} value={margin} />
      </div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:3"]);
  });

  it("reports a house control given neither label nor aria-label", () => {
    const { findings } = labelWithoutField.run(
      files(`<Input type="number" value={qty} onChange={onChange} />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("does not read a placeholder as a name", () => {
    const { findings } = labelWithoutField.run(
      files(
        `<Select value={group} onChange={onChange} placeholder="All groups" options={[]} />`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("leaves a control named by aria-label or aria-labelledby", () => {
    const { findings } = labelWithoutField.run(
      files(`<Input type="number" aria-label="Quantity" value={qty} />
      <input type="range" aria-labelledby="margin-label" value={margin} />`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a control wrapped in a <label>", () => {
    const { findings } = labelWithoutField.run(
      files(`<label className="cursor-pointer">
        Upload
        <input type="file" className="sr-only" />
      </label>`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a control whose id a parent can point its label at", () => {
    // The field renderers take their id as a prop for exactly that — the
    // name lives in a file this rule cannot see.
    const { findings } = labelWithoutField.run(
      files(`<Input id={id} type="text" value={v} onChange={onChange} />
      <input type="file" id="import-file" className="hidden" />`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a control that never enters the accessibility tree", () => {
    const { findings } = labelWithoutField.run(
      files(`<input type="hidden" name="csrf" value={token} />
      <input type="file" className="hidden" onChange={onFile} />
      <input type="submit" value="Save" />`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a control whose props arrive by spread", () => {
    const { findings } = labelWithoutField.run(
      files(
        `<Input type="number" value={value} onChange={onChange} {...props} />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("reads a ProductCombobox placeholder as the name it becomes", () => {
    // ProductCombobox renders its inner input with
    // `aria-label={label ? undefined : placeholder}` — the call site's
    // placeholder is the accessible name, not decoration.
    const { findings } = labelWithoutField.run(
      files(`<ProductCombobox
        value={null}
        onSelect={onSelect}
        search={search}
        placeholder="Link a product"
      />`),
    );
    expect(findings).toEqual([]);
  });

  it("still reports a ProductCombobox nothing names", () => {
    const { findings } = labelWithoutField.run(
      files(
        `<ProductCombobox value={null} onSelect={onSelect} search={search} />`,
      ),
    );
    expect(findings).toEqual(["Fixture.tsx:1"]);
  });
});

/**
 * The screens this pass was written for stay at zero: the pricing slider and
 * its number field, the group filter on the categories page, and the
 * quantity field in a recipe's ingredient row.
 */
const PINNED = [
  "modules/maker/components/PricingCalculator.tsx",
  "modules/inventory/pages/CategoriesPage.tsx",
  "modules/recipes/components/RecipeIngredientRow.tsx",
];

describe("the controls found without a name", () => {
  it("keep theirs", () => {
    const sources = PINNED.map((path) => ({
      path,
      text: readFileSync(join(process.cwd(), "src", path), "utf8"),
    }));

    expect(labelWithoutField.run(sources).findings).toEqual([]);
  });
});
