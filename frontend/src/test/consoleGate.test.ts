import { describe, expect, it } from "vitest";

import {
  assertNoUnexpected,
  baselineKey,
  createConsoleGate,
  failureMessage,
  isGated,
  signatureOf,
  type ConsoleBaseline,
} from "./consoleGate";

describe("consoleGate — what counts as a message", () => {
  it("reads React's format string as the signature", () => {
    // The component name is interpolated and is stable across a stack, but
    // the format string is not: blaming `%s` keeps the signature reproducible.
    expect(
      signatureOf([
        "Warning: An update to %s inside a test was not wrapped in act(...).\n\nWhen testing, code that causes...",
        "FoodCard",
      ]),
    ).toBe(
      "Warning: An update to %s inside a test was not wrapped in act(...).",
    );
  });

  it("keeps the first line of a message that carries a stack", () => {
    // jsdom's "Uncaught [...]" errors arrive with a stack glued on, and a
    // stack's line numbers move with every unrelated edit.
    expect(
      signatureOf([
        "Error: Uncaught [TypeError: boom]\n    at reportException (/app/src/x.ts:12:3)",
      ]),
    ).toBe("Error: Uncaught [TypeError: boom]");
  });

  it("keeps an Error's name and message", () => {
    expect(signatureOf([new TypeError("boom")])).toBe("TypeError: boom");
  });

  it("gates every console.error and React's own console.warn", () => {
    expect(isGated("error", ["anything at all"])).toBe(true);
    expect(isGated("warn", ["Warning: validateDOMNesting(...)"])).toBe(true);
    // Another library's warn is not this gate's business.
    expect(isGated("warn", ["[MSW] some notice"])).toBe(false);
  });

  it("ignores the environment's act false positive", () => {
    expect(
      isGated("error", [
        "The current testing environment is not configured to support act(...)",
      ]),
    ).toBe(false);
  });
});

describe("consoleGate — the baseline is a ceiling", () => {
  const baseline: ConsoleBaseline = {
    "src/modules/thing/Thing.test.tsx": ["Warning: each child"],
  };

  it("absorbs a baselined signature however often it repeats", () => {
    const gate = createConsoleGate(baseline);
    gate.beginTest("/repo/frontend/src/modules/thing/Thing.test.tsx");

    expect(gate.record("error", ["Warning: each child"])).toBe("absorbed");
    expect(gate.record("error", ["Warning: each child"])).toBe("absorbed");
    expect(gate.record("error", ["Warning: each child"])).toBe("absorbed");
    expect(gate.endTest()).toHaveLength(0);
  });

  it("fails a signature the file's baseline does not know", () => {
    const gate = createConsoleGate(baseline);
    gate.beginTest("/repo/frontend/src/modules/thing/Thing.test.tsx");

    expect(gate.record("error", ["Warning: something new"])).toBe("unexpected");
    expect(gate.endTest()[0].signature).toBe("Warning: something new");
  });

  it("does not blame one file for another file's baseline", () => {
    const gate = createConsoleGate(baseline);
    gate.beginTest("/repo/frontend/src/modules/other/Other.test.tsx");

    expect(gate.record("error", ["Warning: each child"])).toBe("unexpected");
    expect(gate.endTest()).toHaveLength(1);
  });

  it("passes non-gated messages through without recording them", () => {
    const gate = createConsoleGate({});
    gate.beginTest("/repo/frontend/src/modules/other/Other.test.tsx");

    expect(gate.record("warn", ["[MSW] notice"])).toBe("pass");
    expect(gate.endTest()).toHaveLength(0);
  });
});

describe("consoleGate — the failure", () => {
  it("names the message and the refresh command", () => {
    const entries = [
      {
        kind: "error" as const,
        signature: "Warning: two children, one key",
        count: 1,
      },
    ];

    expect(() => assertNoUnexpected(entries)).toThrow(/console gate/);
    const message = failureMessage(entries);
    expect(message).toContain("console.error: Warning: two children, one key");
    expect(message).toContain("npm run test:console-baseline");
  });

  it("does not throw on an empty list", () => {
    expect(() => assertNoUnexpected([])).not.toThrow();
  });

  it("keys a test file as repo-relative src/…", () => {
    expect(baselineKey("/repo/frontend/src/modules/thing/Thing.test.tsx")).toBe(
      "src/modules/thing/Thing.test.tsx",
    );
  });
});
