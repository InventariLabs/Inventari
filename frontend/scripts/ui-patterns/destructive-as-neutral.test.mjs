import { describe, expect, it } from "vitest";
import detector from "./destructive-as-neutral.mjs";

const file = (text, path = "Fixture.tsx") => [{ path, text }];

describe("destructive-as-neutral", () => {
  it("reports a neutral-variant button whose i18n key names a destructive act", () => {
    const { findings, considered } = detector.run(
      file(
        `<div>\n  <Button variant="ghost" onClick={go}>\n    {t("common:actions.delete")}\n  </Button>\n</div>`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
    expect(considered).toBe(1);
  });

  it("reads icon-only buttons through the aria-label in the tag", () => {
    const { findings } = detector.run(
      file(`<Button variant="outline" aria-label={t("items.remove")} />`),
    );

    expect(findings).toEqual(["Fixture.tsx:1"]);
  });

  it("covers every neutral variant", () => {
    for (const v of ["ghost", "outline", "secondary", "link"]) {
      const { findings } = detector.run(
        file(`<Button variant="${v}">{t("a.archive")}</Button>`),
      );
      expect(findings).toEqual(["Fixture.tsx:1"]);
    }
  });

  it("accepts ghostDanger", () => {
    const { findings, considered } = detector.run(
      file(`<Button variant="ghostDanger">{t("common:actions.delete")}</Button>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(0);
  });

  it("accepts a neutral button with a neutral label", () => {
    const { findings, considered } = detector.run(
      file(`<Button variant="ghost">{t("common:actions.edit")}</Button>`),
    );

    expect(findings).toEqual([]);
    expect(considered).toBe(1);
  });

  it("judges the key's last segment, not the visible text or a prefix", () => {
    const { findings } = detector.run(
      file(`<Button variant="ghost">{t("delete.title")}Delete</Button>`),
    );

    expect(findings).toEqual([]);
  });

  it("skips a variant given as an expression", () => {
    const { findings } = detector.run(
      file(
        `<Button variant={w.active ? "ghostDanger" : "outline"}>{t("a.deactivate")}</Button>`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("skips the confirmation dialog files", () => {
    const { findings } = detector.run(
      file(
        `<Button variant="outline">{t("common:actions.delete")}</Button>`,
        "components/ConfirmDialog.tsx",
      ),
    );

    expect(findings).toEqual([]);
  });

  it("accepts a documented exception of at least five words", () => {
    const { findings } = detector.run(
      file(
        `{/* ui-pattern: destructive-as-neutral — this tile is the confirmation step itself */}\n<Button variant="outline">{t("a.delete")}</Button>`,
      ),
    );

    expect(findings).toEqual([]);
  });

  it("rejects an exception with a short reason", () => {
    const { findings } = detector.run(
      file(
        `{/* ui-pattern: destructive-as-neutral — fine */}\n<Button variant="outline">{t("a.delete")}</Button>`,
      ),
    );

    expect(findings).toEqual(["Fixture.tsx:2"]);
  });

  it("does not read past the closing tag into the next button's label", () => {
    const { findings } = detector.run(
      file(
        `<Button variant="ghost">{t("a.edit")}</Button>\n<Button variant="ghostDanger">{t("a.delete")}</Button>`,
      ),
    );

    expect(findings).toEqual([]);
  });
});
