import { Suspense, lazy, useMemo } from "react";
import {
  createBrowserRouter,
  createMemoryRouter,
  createRoutesFromElements,
  Route,
  RouterProvider,
} from "react-router-dom";

import LoadingSpinner from "@/components/LoadingSpinner";
import ErrorPage from "@/pages/ErrorPage";

const AttestationPublicPage = lazy(
  () => import("@/modules/equipment/pages/AttestationPublicPage"),
);

/**
 * Everything reachable without an account, and nothing else.
 *
 * These pages used to be routes inside `App`, which meant reaching one loaded
 * the whole application: `App` opened by eagerly globbing every `module.ts`
 * under `src/modules/`, and that registry brought the modules, their API
 * clients and their translations with it. An employee clicking a link in an
 * email to tick off ten pieces of equipment was made to download the
 * warehouse, the recipes and the approvals engine — code they have no account
 * to use and, for the data behind it, no right to see.
 *
 * `main.tsx` picks between this tree and `App` from `window.location` before
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
  const router = useMemo(() => {
    const routes = createRoutesFromElements(
      <Route
        path="/public/attestation/:token"
        element={<AttestationPublicPage />}
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
