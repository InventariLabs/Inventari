import { describe, expect, it } from "vitest";
import nativeDateInput from "./native-date-input.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("native-date-input", () => {
  it("reports a native date input in each spelling of the attribute", () => {
    const { findings } = nativeDateInput.run(
      files(`<input type="date" value={v} />
      <input type='date' />
      <input type={"date"} />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1", "Fixture.tsx:2", "Fixture.tsx:3"]);
  });

  it("leaves DateInput and other input types alone", () => {
    const { findings } = nativeDateInput.run(
      files(`<DateInput value={v} onChange={set} />
      <input type="text" />
      <input type="datetime-local" />`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read prose or a comment as the mistake", () => {
    const { findings } = nativeDateInput.run(
      files(`/** Never render type="date" here. */
      // <input type="date" /> was the old field
      <DateInput value={v} />`),
    );

    expect(findings).toEqual([]);
  });
});
