import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/store/authStore";
import { readJson, writeJson } from "@/lib/localStorage";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";

/** One flag per person: the welcome is for the first visit on this device. */
const greetedKey = (userId: string) => `inventari:greeted:${userId}`;

/**
 * The first-visit answer per person, held for the life of the page.
 *
 * The launcher is free to be thrown away and mounted again inside one visit —
 * finishing onboarding changes the enabled modules, which rebuilds the router
 * and remounts it — so the answer cannot live in a component's state: the
 * remount would re-read a flag the first mount had already written and find
 * the visit spent. A page load starts with the map empty, which is what makes
 * the next load a "welcome back".
 */
const firstVisitThisPage = new Map<string, boolean>();

/** Forget the answers held for this page, as a fresh page load would. */
export function forgetFirstVisits(): void {
  firstVisitThisPage.clear();
}

function isFirstVisit(userId: string | null): boolean {
  if (userId === null) return false;
  let answer = firstVisitThisPage.get(userId);
  if (answer === undefined) {
    answer = !readJson<boolean>(greetedKey(userId), false);
    firstVisitThisPage.set(userId, answer);
  }
  return answer;
}

/**
 * The launcher's title and the line under it.
 *
 * "Welcome back" says there was an earlier visit, and the first one has none
 * to refer to — so that visit is welcomed instead, and told which organization
 * the person has just joined — or, for the one who created it, set up. The answer is read once, on mount, and written
 * afterwards, and remembered for the page (see above), so neither a re-render
 * nor a remount within the visit turns the welcome into a welcome back.
 *
 * "Afterwards" means once the organization has settled and its onboarding is
 * done: on a first login the launcher can mount for a beat while the
 * organization loads, just before the person is sent to onboarding, and that
 * mount delivered no welcome worth counting. The flag stays unset until the
 * welcome that names the organization has actually been on screen.
 */
export function useLauncherGreeting(): { title: string; subtitle: string } {
  const { t } = useTranslation();
  const user = useAuthStore((state) => state.user);
  const { data: org, isFetching } = useOrganization();

  const userId = user?.id ? String(user.id) : null;
  const firstName = user?.full_name?.split(" ")[0] ?? undefined;
  const orgName = org?.name ?? user?.organization_name ?? undefined;

  const [firstVisit] = useState(() => isFirstVisit(userId));
  // Right after onboarding the organization is refetched; until that settles
  // the cached copy may still say onboarding is open.
  const settled = !!org && !isFetching && org.onboarding_completed !== false;
  useEffect(() => {
    if (userId && settled) writeJson(greetedKey(userId), true);
  }, [userId, settled]);

  const title = !firstName
    ? t("launcher:launcher.title", "Home")
    : firstVisit
      ? t("launcher:launcher.welcome", "Welcome, {{name}}", { name: firstName })
      : t("launcher:launcher.welcomeBack", "Welcome back, {{name}}", {
          name: firstName,
        });
  // The founder did not join anything: registration made the organization for
  // them, and the line says so rather than greeting them as a newcomer.
  const founded = !!org?.created_by && String(org.created_by) === userId;
  const subtitle =
    firstVisit && orgName
      ? founded
        ? t(
            "launcher:launcher.createdOrganization",
            "You set up {{organization}}",
            { organization: orgName },
          )
        : t(
            "launcher:launcher.joinedOrganization",
            "You have joined {{organization}}",
            { organization: orgName },
          )
      : t("launcher:launcher.workspaceOverview", "Your workspace overview");

  return { title, subtitle };
}
