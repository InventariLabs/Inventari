/**
 * The two kinds of test that pass whatever the product does: one that looks a
 * raw i18n key up as text, and one with nothing in it that can fail. The gate
 * is run over a scratch `src/` and judged by its exit code and its report.
 */
import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";

let repo;
afterEach(() => repo?.cleanup());

const run = (specs, args = []) => {
  repo = makeRepo();
  repo.write(
    Object.fromEntries(
      Object.entries(specs).map(([name, text]) => [
        `frontend/src/${name}`,
        text,
      ]),
    ),
  );
  return runGate(repo, "lint-test-assertions.mjs", { args });
};

describe("lint-test-assertions", () => {
  it("passes a suite whose tests assert on rendered text", () => {
    const { status, stdout } = run({
      "a.test.tsx": `it("shows the title", () => {\n  render(<A />);\n  expect(screen.getByText("Save")).toBeTruthy();\n});\n`,
    });

    expect(status).toBe(0);
    expect(stdout).toContain("Test assertions: no issues found");
  });

  it("fails on a getByText that matches a raw namespaced key, with file and line", () => {
    const { status, stdout } = run({
      "a.test.tsx": `it("x", () => {\n  expect(screen.getByText("common:form.cancel")).toBeTruthy();\n});\n`,
    });

    expect(status).toBe(1);
    expect(stdout).toContain("Raw i18n keys queried as text (1)");
    expect(stdout).toContain('src/a.test.tsx:2  "common:form.cancel"');
  });

  it("catches a dotted key in a role name, but not a file name or a queryBy absence check", () => {
    const { status, stdout } = run({
      "a.test.tsx": [
        `it("x", () => {`,
        `  expect(screen.getByRole("button", { name: "actions.applyCorrection" })).toBeTruthy();`,
        `  expect(screen.getByText("report.pdf")).toBeTruthy();`,
        `  expect(screen.queryByText("actions.gone")).toBeNull();`,
        `});`,
        ``,
      ].join("\n"),
    });

    expect(status).toBe(1);
    expect(stdout).toContain("Raw i18n keys queried as text (1)");
    expect(stdout).toContain('"actions.applyCorrection"');
    expect(stdout).not.toContain("report.pdf");
    expect(stdout).not.toContain("actions.gone");
  });

  it("lets a line say that a dotted string is data, not a translation", () => {
    const { status } = run({
      "a.test.tsx": `it("x", () => {\n  // not-an-i18n-key: a webhook event type\n  expect(screen.getByText("order.created")).toBeTruthy();\n});\n`,
    });

    expect(status).toBe(0);
  });

  it("fails on a test body with no expectation, naming the test", () => {
    const { status, stdout } = run({
      "a.test.tsx": `it("renders without throwing", () => {\n  render(<A />);\n});\n`,
    });

    expect(status).toBe(1);
    expect(stdout).toContain("Test blocks with no assertion (1)");
    expect(stdout).toContain("src/a.test.tsx:1  renders without throwing");
  });

  it("counts waitFor and a helper named expect* as expectations; skips it.todo", () => {
    const { status } = run({
      "a.test.tsx": [
        `it("waits", async () => {\n  await waitFor(() => ready());\n});`,
        `it("delegates", () => {\n  expectScrollableModal();\n});`,
        `it.todo("later");`,
        ``,
      ].join("\n"),
    });

    expect(status).toBe(0);
  });

  it("does not read files that are not tests", () => {
    const { status } = run({
      "component.tsx": `it("no expectation", () => {});\n`,
    });

    expect(status).toBe(0);
  });

  it("--list prints the findings and still exits 0", () => {
    const { status, stdout } = run(
      { "a.test.tsx": `it("empty", () => {\n  render(<A />);\n});\n` },
      ["--list"],
    );

    expect(status).toBe(0);
    expect(stdout).toContain("1 issue(s).");
  });
});
