import { Suspense, lazy, useMemo } from "react";
import {
  createBrowserRouter,
  createMemoryRouter,
  createRoutesFromElements,
  Route,
  RouterProvider,
} from "react-router-dom";

import { useTranslation } from "react-i18next";

import { useDocumentLanguage } from "@/hooks/useDocumentLanguage";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import LoadingSpinner from "@/components/LoadingSpinner";
import ErrorPage from "@/pages/ErrorPage";

const AttestationPublicPage = lazy(
  () => import("@/modules/equipment/pages/AttestationPublicPage"),
);

/**
 * The attestation page, named in the tab in the language it speaks. Here and
 * not in the page: a module reaches Core through `@/module-sdk`, and the SDK
 * is the application's door, which this tree must not open.
 */
function AttestationRoute() {
  const { t } = useTranslation("equipment");
  useDocumentTitle(t("attestation.public.pageTitle"));
  return <AttestationPublicPage />;
}

/**
 * Everything reachable without an account, and nothing else.
 *
 * These pages stay out of `App`: reaching one must not load the whole
 * application, with the modules, their API clients and their translations. An
 * employee clicking a link in an email to tick off ten pieces of equipment
 * would otherwise download the warehouse, the recipes and the approvals engine
 * — code they have no account to use and, for the data behind it, no right to
 * see.
 *
 * `Root.tsx` picks between this tree and `App` from `window.location` before
 * either is imported, so the two never share a bundle. There is no catch-all
 * here on purpose: `isPublicPath` admits only addresses this file serves, and
 * anything else — including a mistyped `/public/…` — goes to `App` and its
 * own 404.
 *
 * Like `App`, this tree mounts a data router: `errorElement` is armed only
 * there, and a visitor whose route breaks owes the same explanation as
 * anyone else.
 */
export default function PublicApp({
  initialEntries,
}: {
  /**
   * Where the route tree starts. A data router reads the address the browser
   * is already at, so the application never passes this — it exists for
   * tests, which have no address to be at and cannot write one either.
   */
  initialEntries?: string[];
} = {}) {
  // The attestation page speaks the language of `?lang=` or the browser, and
  // the document has to say so (see the hook).
  useDocumentLanguage();
  const router = useMemo(() => {
    const routes = createRoutesFromElements(
      <Route
        path="/public/attestation/:token"
        element={<AttestationRoute />}
        errorElement={<ErrorPage />}
      />,
    );
    return initialEntries
      ? createMemoryRouter(routes, { initialEntries })
      : createBrowserRouter(routes);
  }, [initialEntries]);

  return (
    <Suspense fallback={<LoadingSpinner fullScreen />}>
      <RouterProvider router={router} />
    </Suspense>
  );
}
