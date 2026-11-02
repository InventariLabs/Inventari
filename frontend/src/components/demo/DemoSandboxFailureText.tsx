import { useTranslation } from "react-i18next";
import type { DemoSandboxFailure } from "@/lib/demoSandboxFailure";

/** The plain sentence for a refused demo sandbox. */
export function DemoSandboxFailureText({
  failure,
}: {
  failure: DemoSandboxFailure;
}) {
  const { t } = useTranslation("auth");
  switch (failure) {
    case "capReached":
      return <>{t("demo.capReached")}</>;
    case "poolEmpty":
      return <>{t("demo.poolEmpty")}</>;
    case "tooManyFromHere":
      return <>{t("demo.tooManyFromHere")}</>;
    case "network":
      return <>{t("login.networkError")}</>;
    case "failed":
      return <>{t("demo.failed")}</>;
  }
}
