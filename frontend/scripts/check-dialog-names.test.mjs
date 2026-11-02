/**
 * The scanner decides the verdict, so these pin the shapes it has to read:
 * a prop value containing `>` inside a brace, a self-closing tag, and the
 * difference between having a name and having a description.
 */
import { describe, expect, it } from "vitest";

import {
  isScanned,
  overlayLayerTags,
  sheetTags,
  undeclaredIn,
  undismissibleIn,
  unnamedIn,
} from "./check-dialog-names.mjs";

describe("sheetTags", () => {
  it("reads a tag whose prop value contains a closing angle bracket", () => {
    const text = `<Sheet open onClose={() => setOpen(false)} aria-label="x">`;
    expect(sheetTags(text)).toEqual([text]);
  });

  it("reads a multi-line tag", () => {
    const text = ["<Sheet", "  open", '  aria-label="x"', ">"].join("\n");
    expect(sheetTags(text)).toHaveLength(1);
  });

  it("does not mistake SheetBody for a dialog", () => {
    expect(sheetTags("<SheetBody className='p-5'>")).toEqual([]);
  });
});

describe("unnamedIn", () => {
  it("accepts aria-label", () => {
    expect(unnamedIn("a.tsx", '<Sheet open aria-label={t("x")}>')).toEqual([]);
  });

  it("accepts aria-labelledby", () => {
    expect(unnamedIn("a.tsx", '<Sheet open aria-labelledby="h">')).toEqual([]);
  });

  it("reports a dialog with only a description", () => {
    // The category modal had exactly this: its heading id was wired to
    // aria-describedby, so it had a description and no name.
    expect(unnamedIn("a.tsx", '<Sheet open aria-describedby="h">')).toEqual([
      "a.tsx",
    ]);
  });

  it("reports each unnamed dialog in a file", () => {
    const text = "<Sheet open>\n<Sheet open>";
    expect(unnamedIn("a.tsx", text)).toEqual(["a.tsx", "a.tsx"]);
  });
});

describe("isScanned", () => {
  it("skips specs and the Sheet component itself", () => {
    expect(isScanned("modules/x/Y.tsx")).toBe(true);
    expect(isScanned("modules/x/Y.test.tsx")).toBe(false);
    expect(isScanned("components/ui/Sheet.tsx")).toBe(false);
    expect(isScanned("modules/x/y.ts")).toBe(false);
  });
});

describe("undeclaredIn", () => {
  it("reports the shape the rating screen had: fullscreen, no role", () => {
    const text =
      '<div className="fixed inset-0 z-[var(--z-fullscreen)] bg-surface">';
    expect(undeclaredIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("accepts a fullscreen surface that declares the role", () => {
    const text = [
      "<div",
      '  role="dialog"',
      '  aria-modal="true"',
      '  className="fixed inset-0 z-[var(--z-fullscreen)] bg-surface"',
      ">",
    ].join("\n");
    expect(undeclaredIn("a.tsx", text)).toEqual([]);
  });

  it("leaves the other modal layers alone", () => {
    // A backdrop on `--z-modal` is not a screen standing in front of the
    // app: most of them hold a named panel and declare nothing themselves.
    const text =
      '<div className="fixed inset-0 z-[var(--z-modal)] bg-black/50">';
    expect(undeclaredIn("a.tsx", text)).toEqual([]);
  });
});

describe("overlayLayerTags", () => {
  it("does not read a tier lookup table as an overlay", () => {
    // SearchableCombobox maps every tier to its class; the string is there,
    // the overlay is not.
    const text = 'const M = { fullscreen: "z-[var(--z-fullscreen)]" };';
    expect(overlayLayerTags(text)).toEqual([]);
  });

  it("reads every modal layer, not only the fullscreen one", () => {
    for (const layer of ["modal", "modal-nested", "confirm", "fullscreen"]) {
      const tag = `<div className="fixed inset-0 z-[var(--z-${layer})] bg-black/50">`;
      expect(overlayLayerTags(tag)).toEqual([tag]);
    }
  });

  it("reads the layer when it is set through a style", () => {
    // `style={{ zIndex: 'var(--z-fullscreen)' }}` is the idiom Sheet itself
    // uses; a rule that read only class names looked straight past it.
    const tag = '<div role="dialog" style={{ zIndex: "var(--z-fullscreen)" }}>';
    expect(overlayLayerTags(tag)).toEqual([tag]);
  });

  it("does not read an unrelated layer as an overlay", () => {
    const tag = '<div style={{ zIndex: "var(--z-notification)" }}>';
    expect(overlayLayerTags(tag)).toEqual([]);
  });
});

describe("undismissibleIn", () => {
  /** A fullscreen surface that declares the role — the shape both rules read. */
  const declared =
    '<div role="dialog" aria-modal="true" className="fixed inset-0 z-[var(--z-fullscreen)]">';

  it("reports the shape the storage wizard had: the role, and no way out", () => {
    // Declared, named, focus-trapped — and the keyboard pressed at it did
    // nothing but move focus to the cross. The role made the naming rule
    // happy, and nothing asked what happened to the key.
    const text = `${declared}\n<Button onClick={onClose}><X size={18} /></Button>`;
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("accepts a fullscreen dialog that answers Escape itself", () => {
    const text = [
      "function Screen() {",
      `  ${declared}`,
      "  useEffect(() => {",
      '    const h = (e) => { if (e.key === "Escape") onClose(); };',
      '    document.addEventListener("keydown", h);',
      "  });",
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual([]);
  });

  it("accepts a fullscreen dialog rendered through the shared Sheet", () => {
    // Delegation is the answer the gate already gives for the name: Sheet
    // brings the role, the trap and the key with it.
    const text = [
      "function Screen() {",
      `  ${declared}`,
      '  return <Sheet open onClose={onClose} aria-label="x" />;',
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual([]);
  });

  it("accepts a Radix dialog, whose primitive brings the key — when it is used", () => {
    const text = [
      'import * as DialogPrimitive from "@radix-ui/react-dialog";',
      "function Screen() {",
      `  return <DialogPrimitive.Content ${declared} />;`,
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual([]);
  });

  it("does not take a passing mention of the key for the exit (A)", () => {
    // The first version of the rule read the whole file: one comment saying
    // "this screen deliberately ignores 'Escape'" vouched for the overlay
    // under it, and the gate called a keyboard trap clean.
    const text = `${declared}\n// the rating screen deliberately ignores 'Escape'`;
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("does not let one component vouch for another (A)", () => {
    // Evidence counts for the component that renders the overlay. A hook or
    // a sibling component in the same file that answers Escape is not the
    // surface under inspection.
    const text = [
      "function List() {",
      `  return ${declared};`,
      "}",
      "function Editor() {",
      "  useEffect(() => {",
      '    const h = (e) => { if (e.key === "Escape") close(); };',
      '    document.addEventListener("keydown", h);',
      "  });",
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("sees the layer when it is written as a style (B)", () => {
    // Sheet itself sets its layer through `style`; a rule that read only
    // class names could not see the idiom its own primitive uses.
    const text = [
      "function Screen() {",
      '  return <div role="dialog" aria-modal="true" style={{ zIndex: "var(--z-fullscreen)" }} />;',
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("sees every modal layer, not only the fullscreen one (C)", () => {
    for (const layer of ["modal", "modal-nested", "confirm"]) {
      const text = [
        "function Screen() {",
        `  return <div role="dialog" aria-modal="true" className="fixed inset-0 z-[var(--z-${layer})]" />;`,
        "}",
      ].join("\n");
      expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
    }
  });

  it("does not count an import nobody uses (D)", () => {
    const text = [
      'import { Dialog } from "@radix-ui/react-dialog";',
      "function Screen() {",
      `  return ${declared};`,
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("leaves a fullscreen element with no role to the rule that owns it", () => {
    const text =
      '<div className="fixed inset-0 z-[var(--z-fullscreen)] bg-surface">';
    expect(undismissibleIn("a.tsx", text)).toEqual([]);
    expect(undeclaredIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("does not report a dialog somebody else's tag declares", () => {
    // The `<Sheet>` three lines above renders the role; the fullscreen class
    // here is a wrapper around it and declares nothing of its own.
    const text = [
      "<Sheet open={open} onClose={onClose} aria-label={t('title')}>",
      '<div className="fixed inset-0 z-[var(--z-fullscreen)]">',
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual([]);
  });

  it("reads a tag with a dot in its name", () => {
    // ConfirmDialog writes its overlay as <AlertDialogPrimitive.Overlay>.
    const text = [
      "function Screen() {",
      '  return <AlertDialogPrimitive.Overlay role="dialog" style={{ zIndex: "var(--z-confirm)" }} />;',
      "}",
    ].join("\n");
    expect(overlayLayerTags(text)).toHaveLength(1);
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("does not take a layout piece named Dialog* for the exit", () => {
    const text = [
      "function Screen() {",
      `  return <div>${declared}<AlertDialogFooter /></div>;`,
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
  });

  it("holds role=alertdialog to the same exit as role=dialog", () => {
    const text = [
      "function Screen() {",
      '  return <div role="alertdialog" aria-modal="true" className="fixed inset-0 z-[var(--z-confirm)]" />;',
      "}",
    ].join("\n");
    expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
    const fullscreen = text.replace("confirm", "fullscreen");
    expect(undeclaredIn("a.tsx", fullscreen)).toEqual([]);
    expect(undismissibleIn("a.tsx", fullscreen)).toEqual(["a.tsx"]);
  });

  it("sees a layer written as a number", () => {
    for (const z of ['className="fixed inset-0 z-50"', 'className="z-[150]"', 'style={{ zIndex: 400 }}']) {
      const text = `function S() {\n  return <div role="dialog" ${z} />;\n}`;
      expect(undismissibleIn("a.tsx", text)).toEqual(["a.tsx"]);
    }
    // A small number on an element that does not cover the viewport is a
    // sticky header, not a modal.
    const sticky = '<div role="dialog" className="sticky top-0 z-10" />';
    expect(undismissibleIn("a.tsx", sticky)).toEqual([]);
    expect(
      undeclaredIn("a.tsx", '<div style={{ zIndex: 400 }} className="fixed">'),
    ).toEqual(["a.tsx"]);
  });
});
