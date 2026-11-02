import { describe, expect, it } from "vitest";
import errorMessageAsCopy from "./error-message-as-copy.mjs";

const file = (text) => [{ path: "modules/things/ThingForm.tsx", text }];

describe("error-message-as-copy", () => {
  it("reports a failed request's own message put on screen", () => {
    const { findings } = errorMessageAsCopy.run(
      file(`onError: (err) => toast.error(err.message)`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("sees through the cast that hides the name", () => {
    const { findings } = errorMessageAsCopy.run(
      file(`toast.error((error as Error).message);`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:1"]);
  });

  it("leaves a message that is not a failure's", () => {
    const { findings } = errorMessageAsCopy.run(
      file(`toast.success(response.message);`),
    );

    expect(findings).toEqual([]);
  });

  it("excuses a read that carries a reason", () => {
    const { findings } = errorMessageAsCopy.run(
      file(`function unwrap(error) {
  // ui-pattern: error-message-as-copy — this class exists to mark a message
  // composed for the reader rather than for the log
  return error instanceof ReadableError ? error.message : null;
}`),
    );

    expect(findings).toEqual([]);
  });

  it("does not accept a marker with nothing behind it", () => {
    // A path list with no argument attached is where a rule goes to be
    // forgotten; the marker has to be an actual sentence.
    const { findings } = errorMessageAsCopy.run(
      file(`function unwrap(error) {
  // ui-pattern: error-message-as-copy
  return error.message;
}`),
    );

    expect(findings).toEqual(["modules/things/ThingForm.tsx:3"]);
  });

  it("does not let one marker excuse the whole file", () => {
    const lines = [
      "function unwrap(error) {",
      "  // ui-pattern: error-message-as-copy — this one carries a sentence",
      "  // written for the reader rather than for the log",
      "  return error instanceof ReadableError ? error.message : null;",
      "}",
      ...Array.from(
        { length: 30 },
        () => "// filler line to push past the window",
      ),
      "const shown = err.message;",
    ];

    const { findings } = errorMessageAsCopy.run(file(lines.join("\n")));

    expect(findings).toEqual(["modules/things/ThingForm.tsx:36"]);
  });
});
