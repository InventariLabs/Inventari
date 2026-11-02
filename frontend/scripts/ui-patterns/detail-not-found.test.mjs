import { describe, expect, it } from "vitest";
import detailNotFound from "./detail-not-found.mjs";

const page = (text) => [
  { path: "modules/things/pages/ThingDetailPage.tsx", text },
];

describe("detail-not-found", () => {
  it("reports a detail page whose error branch swallows the 404", () => {
    const { findings } = detailNotFound.run(
      page(`if (isError || !thing) {
        return <p>{t("detail.notFound")}</p>;
      }`),
    );

    expect(findings).toEqual(["modules/things/pages/ThingDetailPage.tsx"]);
  });

  it("reports a page that splits the two but renders its own not-found", () => {
    const { findings } = detailNotFound.run(
      page(`if (isError && !isNotFoundError(error)) return <QueryError />;
      if (!thing) return <div>{t("detail.notFound")}</div>;`),
    );

    expect(findings).toEqual(["modules/things/pages/ThingDetailPage.tsx"]);
  });

  it("leaves a page that splits the two and renders the shared state", () => {
    const { findings } = detailNotFound.run(
      page(`if (isError && !isNotFoundError(error)) return <QueryError />;
      if (!thing) return <RecordNotFound title={t("detail.notFound")} />;`),
    );

    expect(findings).toEqual([]);
  });

  it("does not claim a page that reads no record", () => {
    const { findings } = detailNotFound.run(page(`return <ThingWizard />;`));

    expect(findings).toEqual([]);
  });

  it("looks only at detail pages", () => {
    const { considered } = detailNotFound.run([
      { path: "modules/things/pages/ThingsPage.tsx", text: "isError" },
      { path: "components/ui/Card.tsx", text: "isError" },
    ]);

    expect(considered).toBe(0);
  });
});
