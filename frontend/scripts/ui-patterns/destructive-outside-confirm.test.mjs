import { describe, expect, it } from "vitest";
import detector from "./destructive-outside-confirm.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];

describe("destructive-outside-confirm", () => {
  it("reports a filled destructive Button with its path:line", () => {
    const { findings, considered } = detector.run(
      file(`<div>\n  <Button variant="destructive" onClick={() => go()}>x</Button>\n</div>`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reports the danger spelling too", () => {
    const { findings } = detector.run(file(`<Button variant="danger">x</Button>`));

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("accepts ghostDanger and other variants", () => {
    const { findings, considered } = detector.run(
      file(`<Button variant="ghostDanger">x</Button>\n<Button variant="outline">y</Button>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("ignores variant props on components that are not Button", () => {
    const { findings } = detector.run(
      file(`<ConfirmDialog variant="danger" />\n<Badge variant="danger">x</Badge>`),
    );

    expect(findings).toEqual([]);
  });

  it("skips the confirmation dialog files themselves", () => {
    const text = `<Button variant="destructive">Delete</Button>`;

    expect(detector.run(file(text, "components/ConfirmDialog.tsx")).findings).toEqual([]);
    expect(
      detector.run(file(text, "components/ConfirmationDialog.tsx")).findings,
    ).toEqual([]);
  });

  it("accepts a documented exception of at least five words just above", () => {
    const { findings } = detector.run(
      file(
        `{/* ui-pattern: filled-destructive — this is the confirmation step, the reason field makes it one */}\n<Button variant="destructive">x</Button>`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("rejects an exception whose reason is too short", () => {
    const { findings } = detector.run(
      file(
        `{/* ui-pattern: filled-destructive — because */}\n<Button variant="destructive">x</Button>`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });

  it("does not let an exception far above cover a later button", () => {
    const filler = "x".repeat(600);
    const { findings } = detector.run(
      file(
        `{/* ui-pattern: filled-destructive — a perfectly good five word reason */}\n${filler}\n<Button variant="destructive">x</Button>`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:3"]);
  });
});
