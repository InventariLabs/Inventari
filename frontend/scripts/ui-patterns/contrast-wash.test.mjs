import { describe, expect, it } from "vitest";
import contrastWash from "./contrast-wash.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];

describe("contrast-wash", () => {
  it("reports the original shape: text-amber-500 on bg-amber-500/10", () => {
    const { findings } = contrastWash.run(
      files(
        `<div className="border border-amber-500/30 bg-amber-500/10 text-amber-500" />`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("reports the pair whichever order the classes come in", () => {
    const { findings } = contrastWash.run(
      files(`<div className="text-primary-600 bg-primary-500/10" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("reads the strings a severity helper returns, not only className", () => {
    const { findings } = contrastWash.run(
      files(
        `const getSeverityColor = (s: string) => {
  switch (s) {
    case "critical":
      return "bg-red-500/10 border-red-500/30 text-red-500";
    default:
      return "bg-surface-raised border-border text-on-secondary";
  }
};`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:4"]);
  });

  it("ignores a wash that only appears on hover — the static pairing of that text is not this rule's finding", () => {
    const { findings } = contrastWash.run(
      files(
        `<button className="text-red-400 hover:bg-red-500/10 border border-red-500/40" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("leaves the blessed tint pair alone", () => {
    const { findings } = contrastWash.run(
      files(
        `<div className="bg-amber-50 border border-amber-200 text-on-warning dark:bg-amber-500/10 dark:border-amber-500/20" />
         <div className="bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500" />
         <p className="text-sm text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a dark:-prefixed wash and dark:-prefixed text alone", () => {
    const { findings } = contrastWash.run(
      files(
        `<div className="border border-red-300 text-red-600 dark:text-red-400 dark:border-red-500/40 hover:bg-red-50 dark:hover:bg-red-500/10" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("does not flag the dark-only rescue under a hover: prefix", () => {
    const { findings } = contrastWash.run(
      files(
        `<button className="text-on-muted hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("leaves text-700 and up — the blessed text steps — alone", () => {
    const { findings } = contrastWash.run(
      files(
        `<div className="bg-red-500/10 text-red-700" />
         <div className="bg-blue-500/10 text-blue-800" />`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("does not flag different hues on one element", () => {
    const { findings } = contrastWash.run(
      files(`<div className="bg-amber-500/10 text-red-500" />`),
    );

    expect(findings).toEqual([]);
  });

  it("does not read the prose explaining the mistake as the mistake", () => {
    const { findings } = contrastWash.run(
      files(`/**
       * bg-amber-500/10 text-amber-500 is what this replaced (1.99:1).
       */
      <div className="bg-amber-50 text-on-warning" />`),
    );

    expect(findings).toEqual([]);
  });

  it("honours a contrast-wash exception that carries its reason", () => {
    const { findings } = contrastWash.run(
      files(`{/* ui-pattern: contrast-wash — the swatch shows the colour the
          user picked as their widget's identity; it carries no text */}
      <div className="bg-purple-500/10 text-purple-500" />`),
    );

    expect(findings).toEqual([]);
  });

  it("rejects an exception whose reason is not a sentence", () => {
    const { findings } = contrastWash.run(
      files(`{/* ui-pattern: contrast-wash — looks nice */}
      <div className="bg-purple-500/10 text-purple-500" />`),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });
});
