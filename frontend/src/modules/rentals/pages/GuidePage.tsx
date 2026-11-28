import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { Card, buttonVariants, useModulePageHeader } from "@/module-sdk";

import { RentalsTabs } from "../components/RentalsTabs";

const STEPS = [
  { title: "guide.steps.book.title", body: "guide.steps.book.body" },
  { title: "guide.steps.kits.title", body: "guide.steps.kits.body" },
  { title: "guide.steps.borrower.title", body: "guide.steps.borrower.body" },
  { title: "guide.steps.handOut.title", body: "guide.steps.handOut.body" },
  { title: "guide.steps.takeBack.title", body: "guide.steps.takeBack.body" },
  { title: "guide.steps.late.title", body: "guide.steps.late.body" },
] as const;

export default function GuidePage() {
  const { t } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({ title: t("guide.title"), backTo: "/rentals" });
  }, [setHeader, t]);

  return (
    <div className="flex flex-col gap-5">
      <RentalsTabs />
      <Card className="px-4 py-4">
        <h2 className="m-0 text-xl font-semibold">{t("guide.heading")}</h2>
        <p className="mb-0 mt-2 text-sm text-zinc-600">{t("guide.intro")}</p>
      </Card>
      <ol className="m-0 flex list-none flex-col gap-4 p-0">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <Card className="flex gap-3 px-4 py-4">
              <span className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-teal-50 text-sm font-semibold text-teal-800">
                {index + 1}
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <h2 className="m-0 text-base font-semibold">{t(step.title)}</h2>
                <p className="m-0 text-sm text-zinc-600">{t(step.body)}</p>
              </div>
            </Card>
          </li>
        ))}
      </ol>
      <Card className="px-4 py-4">
        <h2 className="m-0 text-base font-semibold">{t("guide.rulesTitle")}</h2>
        <ul className="mb-0 mt-2 flex list-disc flex-col gap-1 pl-5 text-sm text-zinc-600">
          <li>{t("guide.rules.buffer")}</li>
          <li>{t("guide.rules.block")}</li>
          <li>{t("guide.rules.overdue")}</li>
          <li>{t("guide.rules.partial")}</li>
          <li>{t("guide.rules.kits")}</li>
          <li>{t("guide.rules.reminders")}</li>
          <li>{t("guide.rules.bookAgain")}</li>
        </ul>
      </Card>
      <div>
        <Link to="/rentals" className={buttonVariants({ variant: "outline" })}>
          {t("guide.back")}
        </Link>
      </div>
    </div>
  );
}
