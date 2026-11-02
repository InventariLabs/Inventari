/**
 * The gate has teeth: a real React warning stops the test.
 *
 * This file deliberately renders a `<div>` inside a `<p>` — exactly the kind
 * of green-but-wrong screen the gate exists for. The warning is fed to a gate
 * built with an empty baseline, not to the run's own gate, so the suite stays
 * green while the failure path itself is asserted here.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { assertNoUnexpected, createConsoleGate } from "./consoleGate";

const FILE = "src/test/consoleGate.teeth.test.tsx";

describe("consoleGate — a real React warning trips it", () => {
  it("fails with a readable message when React logs console.error", () => {
    const gate = createConsoleGate({});
    gate.beginTest(FILE);
    const originalConsoleError = console.error;
    console.error = (...args: unknown[]) => {
      gate.record("error", args);
    };
    try {
      render(
        <p>
          <div>invalid nesting</div>
        </p>,
      );
    } finally {
      console.error = originalConsoleError;
    }

    const unexpected = gate.endTest();
    const nesting = unexpected.find((entry) =>
      entry.signature.includes("validateDOMNesting"),
    );
    expect(nesting).toBeDefined();
    expect(() => assertNoUnexpected(unexpected)).toThrow(/validateDOMNesting/);
    expect(() => assertNoUnexpected(unexpected)).toThrow(
      /npm run test:console-baseline/,
    );
  });
});
