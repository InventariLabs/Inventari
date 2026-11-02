import { classNameOf, lineAt, openingTags } from "./lib.mjs";

/** Controls that draw their own label above themselves. */
const FIELDS = [
  "Input",
  "Textarea",
  "Select",
  "NativeSelect",
  "DateInput",
  "SearchableCombobox",
];

/** A row that puts fields side by side. */
const SIDE_BY_SIDE = /(?:^|\s)(?:[a-z0-9-]+:)?grid-cols-[2-4](?:\s|$)/;

/** Any explicit answer to "where in the row does a short child sit?". */
const ALIGNED =
  /(?:^|\s)(?:[a-z0-9-]+:)?items-(?:end|start|center|baseline|stretch)(?:\s|$)/;

/** How far past the opening tag a row's own children can reasonably reach. */
const ROW_SPAN = 2000;

export default {
  name: "field-row-baseline",
  says:
    "Two labelled fields side by side line up by their tops, so the one " +
    "whose label wraps to a second line pushes its own control below its " +
    "neighbour's. The label's length is a property of the language, not of " +
    "the field: an English row that looks right is a Polish row that does " +
    "not.",
  advice:
    "Add `items-end` to the row. The controls then sit on one line whatever\n" +
    "the labels above them do. `items-start` is the deliberate opposite and\n" +
    "counts as an answer; no `items-*` at all is the accident.",

  run(files) {
    const considered = new Set();
    const findings = [];

    for (const file of files) {
      const rows = [...openingTags(file.text, "div")].filter(({ tag }) =>
        SIDE_BY_SIDE.test(classNameOf(tag) ?? ""),
      );
      if (rows.length === 0) continue;
      considered.add(file.path);

      for (const [position, { tag, index }] of rows.entries()) {
        if (ALIGNED.test(classNameOf(tag) ?? "")) continue;

        // The row's own children end where the next row begins — a nested
        // grid belongs to itself, not to the one around it.
        const next = rows[position + 1];
        const end = Math.min(
          next ? next.index : file.text.length,
          index + ROW_SPAN,
        );
        const body = file.text.slice(index + tag.length, end);

        const labelled = FIELDS.flatMap((field) => [
          ...openingTags(body, field),
        ]).filter(({ tag: fieldTag }) => /\slabel[=\s]/.test(fieldTag));

        if (labelled.length < 2) continue;
        findings.push(`${file.path}:${lineAt(file.text, index)}`);
      }
    }

    return { considered: considered.size, findings };
  },
};
