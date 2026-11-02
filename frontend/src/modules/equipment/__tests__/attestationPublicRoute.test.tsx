import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import PublicApp from "@/PublicApp";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

/**
 * The one screen in this product opened by somebody with no account.
 *
 * It never rendered. The pass measured the document returning 200 and the
 * body sitting on the loading spinner past forty-five seconds, three times
 * over — and the cause was one line away from the comment explaining it:
 * `App` skips `checkAuth()` on a public route, and `checkAuth()` is the only
 * thing that clears the store's initial `isLoading: true`. The guard above
 * the routes then waited for a session the page had just decided not to ask
 * for.
 *
 * The second half is what the visitor was made to download to get there. The
 * public route lived inside `App`, whose first statement eagerly globbed every
 * `module.ts` under `src/modules/`, so reaching a page that shows ten asset
 * names pulled in every module of the application — including the ones whose
 * data this reader has no right to see. `PublicApp` is a separate tree now;
 * the boundary itself is held by `npm run check:public-bundle`, which walks
 * the import graph, because a module graph assembled by the test runner is
 * not the one the browser downloads.
 */
const ASSET = {
  id: "resp-1",
  token: "tok-1",
  status: "PENDING",
  assignee_email: "nina@example.com",
  campaign_name: "Annual check",
  items: [
    {
      assignment_id: "asg-1",
      item_id: "itm-1",
      item_name: "ThinkPad T14",
      serial_number: "SN-9911",
    },
  ],
};

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/public/attestation/tok-1", () => HttpResponse.json(ASSET)),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPublic(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      {/* `PublicApp` mounts its own data router; a `<MemoryRouter>` around it
          would be a second `<Router>`, which is an invariant violation. */}
      <PublicApp initialEntries={[path]} />
    </QueryClientProvider>,
  );
}

describe("the public attestation route", () => {
  it("renders the assets to confirm, without waiting for a session", async () => {
    renderPublic("/public/attestation/tok-1");

    expect(await screen.findByText(/thinkpad t14/i)).toBeInTheDocument();
    expect(screen.getByText(/SN-9911/)).toBeInTheDocument();
  });

  it("offers the confirm action in words, not in i18n keys", async () => {
    renderPublic("/public/attestation/tok-1");

    // Two things at once. The page hung on the spinner because it waited for
    // a session it had just decided not to ask for, so an action proves it is
    // settled. And the labels must resolve: the `equipment` namespace is not
    // the module registry's to hand out in this tree — it comes with the i18n
    // bundles — so a key nothing loaded would read
    // "attestation.public.confirmButton".
    expect(
      await screen.findByRole("button", { name: /i have this asset/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/attestation\.public\./)).not.toBeInTheDocument();
  });
});
