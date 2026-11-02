import { describe, expect, it } from "vitest";
import { findViolations } from "./check-on-error-refusals.mjs";

const file = (text) => [{ path: "modules/things/ThingForm.tsx", text }];

describe("check-on-error-refusals", () => {
  it("catches the arrow that throws the refusal away", () => {
    const findings = findViolations(
      file(`useX({ onError: () => toast.error("Request failed") })`),
    );
    expect(findings.length).toBe(1);
  });

  it("catches an underscore-named parameter that is never read", () => {
    const findings = findViolations(
      file(`useX({ onError: (_err) => toast.error("stała") })`),
    );
    expect(findings.length).toBe(1);
  });

  it("catches a classic function with no parameter", () => {
    const findings = findViolations(
      file(`useX({ onError: function () { toast.error("stała"); } })`),
    );
    expect(findings.length).toBe(1);
  });

  it("catches a handler that takes the error and ignores it", () => {
    const findings = findViolations(
      file(`useX({ onError: (err) => toast.error("stała") })`),
    );
    expect(findings.length).toBe(1);
  });

  it("catches the empty parameter list written across two lines", () => {
    const findings = findViolations(
      file("useX({\n  onError: (\n  ) => toast.error('stała'),\n})"),
    );
    expect(findings.length).toBe(1);
  });

  it("catches the method shorthand", () => {
    const findings = findViolations(
      file(`useX({\n  onError() { toast.error("stała"); },\n})`),
    );
    expect(findings.length).toBe(1);
  });

  it("catches a zero-parameter reference resolvable in the same file", () => {
    const findings = findViolations(
      file(
        "function handleRefusal() { toast.error('stała'); }\n" +
          "useX({ onError: handleRefusal })",
      ),
    );
    expect(findings.length).toBe(1);
  });

  it("passes a handler that reads the refusal through extractApiError", () => {
    const findings = findViolations(
      file(
        `useX({ onError: (err) => toast.error(extractApiError(err, "fallback")) })`,
      ),
    );
    expect(findings).toEqual([]);
  });

  it("passes a handler that names the error and logs it deliberately", () => {
    const findings = findViolations(
      file(`useX({ onError: (err) => { console.error(err); } })`),
    );
    expect(findings).toEqual([]);
  });

  it("passes the type signature (() => void) — a signature is not a handler", () => {
    const findings = findViolations(
      file(`interface Options { onError: () => void; retry: boolean }`),
    );
    expect(findings).toEqual([]);
  });
});
