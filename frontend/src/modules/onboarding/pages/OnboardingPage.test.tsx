import { afterEach, describe, it, expect, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { CURRENCY_CODES } from "@/lib/currencies";
import { useAuthStore } from "@/store/authStore";
import OnboardingPage from "./OnboardingPage";
import { OnboardingGuard } from "../components/OnboardingGuard";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const profiles = [
  {
    id: "food_home",
    name: "Food & Home",
    description: "d",
    default_modules: ["items"],
  },
  {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "d",
    default_modules: ["items"],
  },
  {
    id: "clean_core",
    name: "Custom",
    description: "d",
    default_modules: ["items"],
  },
];

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/onboarding" element={<OnboardingPage />} />
          <Route
            path="/"
            element={
              <OnboardingGuard>
                <div>HOME_REACHED</div>
              </OnboardingGuard>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...view, qc };
}

/**
 * Picking a mode no longer applies it: the reader passes through a second
 * step that says what the mode starts with. Every test that used to click
 * "Get started" straight after a card now walks both.
 */
async function finishSetup() {
  const next = screen.queryByRole("button", { name: /continue/i });
  if (next) await userEvent.click(next);
  await userEvent.click(screen.getByRole("button", { name: /get started/i }));
}

/**
 * After confirming a profile, the org query must be refetched (awaited)
 * BEFORE navigating, otherwise OnboardingGuard still sees the stale
 * `onboarding_completed: false` and bounces the user back to /onboarding.
 */
describe("OnboardingPage — navigate past guard", () => {
  it("reaches '/' (guard lets it through) after profile setup", async () => {
    let onboardingCompleted = false;
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          onboarding_completed: onboardingCompleted,
        }),
      ),
      http.post("*/api/v1/onboarding/setup", () => {
        onboardingCompleted = true;
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );

    renderAt("/onboarding");

    // Select a profile, then confirm.
    const card = await screen.findByRole("button", { name: /Food & Home/i });
    await userEvent.click(card);
    await finishSetup();

    // Guard must see the refreshed org and let us through to the home route.
    await waitFor(() => {
      expect(screen.getByText("HOME_REACHED")).toBeInTheDocument();
    });
  });
});

/**
 * The wizard translates its own headings but used to render the three profile
 * cards — the only content the choice rests on — straight from the English
 * registry. This is the first screen a new user sees.
 */
describe("OnboardingPage — profile cards speak the user's language", () => {
  it("names all three workspace modes in Polish, with no English left over", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    await withLanguage("pl", async () => {
      const { unmount } = renderAt("/onboarding");
      expect(
        await screen.findByRole("button", { name: /Dom i jedzenie/ }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Sprzęt i magazyn/ }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Własny/ }),
      ).toBeInTheDocument();
      // One concept, one word: the heading says what the error beside it says.
      expect(screen.getByText("Wybierz tryb pracy")).toBeInTheDocument();

      for (const english of [
        "Food & Home",
        "Equipment & Warehouse",
        "Custom",
      ]) {
        expect(screen.queryByText(english)).not.toBeInTheDocument();
      }
      unmount();
    });
  });
});

/**
 * A 403 on setup means this account will never be allowed to apply a profile.
 * The screen used to answer it with "please try again" — advice that cannot
 * work — and no way off the page.
 */
describe("OnboardingPage — a refusal that will not change", () => {
  it("explains a 403 and offers the way out", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.post(
        "*/api/v1/onboarding/setup",
        () => new HttpResponse(null, { status: 403 }),
      ),
    );

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    expect(
      await screen.findByText(/only an administrator can set this up/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign out/i }),
    ).toBeInTheDocument();
  });
});

/** The organization's currency is permanent; USD for a Polish reader is a
 *  choice nobody made. */
describe("OnboardingPage — currency follows the interface language", () => {
  it("opens on PLN for a Polish interface", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    await withLanguage("pl", async () => {
      const { unmount } = renderAt("/onboarding");
      const select = (await screen.findByLabelText(
        /waluta/i,
      )) as HTMLSelectElement;
      expect(select.value).toBe("PLN");
      unmount();
    });
  });

  it("offers the one currency list the rest of the application offers", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    renderAt("/onboarding");

    const select = (await screen.findByLabelText(
      /currency/i,
    )) as HTMLSelectElement;
    const offered = Array.from(select.querySelectorAll("option")).map(
      (option) => option.value,
    );
    expect(offered).toEqual([...CURRENCY_CODES]);
  });
});

/**
 * The currency an organization is created with is the one it keeps, and the
 * two tests above only prove the select renders: a decorative picker whose
 * value never reaches the request would pass both of them.
 */
describe("OnboardingPage — the chosen currency reaches the request", () => {
  it("sends the currency the reader picked, not the guessed one", async () => {
    let body: { profile_id?: string; currency?: string } | null = null;
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        body = (await request.json()) as {
          profile_id: string;
          currency: string;
        };
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );

    renderAt("/onboarding");

    const select = (await screen.findByLabelText(
      /currency/i,
    )) as HTMLSelectElement;
    await userEvent.selectOptions(select, "SEK");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ profile_id: "food_home", currency: "SEK" });
  });
});

/**
 * The country picks the tax rate and the partner rule, and Settings was the
 * only place that set it. The select has to be offered, guessed from the
 * browser, and its value has to reach the request.
 */
describe("OnboardingPage — the organization's country", () => {
  function useSetupCapture() {
    const seen: { body: { country?: string } | null } = { body: null };
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        seen.body = (await request.json()) as { country?: string };
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );
    return seen;
  }

  afterEach(() => vi.restoreAllMocks());

  it("opens on the country the browser locale suggests and sends it", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    const seen = useSetupCapture();

    renderAt("/onboarding");

    const select = (await screen.findByLabelText(
      /country/i,
    )) as HTMLSelectElement;
    expect(select.value).toBe("DE");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).toMatchObject({ country: "DE" });
  });

  it("sends the country the reader picked over the guess", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    const seen = useSetupCapture();

    renderAt("/onboarding");

    const select = (await screen.findByLabelText(
      /country/i,
    )) as HTMLSelectElement;
    await userEvent.selectOptions(select, "GB");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).toMatchObject({ country: "GB" });
  });

  it("sends no country when the reader leaves it unset", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("xx");
    const seen = useSetupCapture();

    renderAt("/onboarding");

    const select = (await screen.findByLabelText(
      /country/i,
    )) as HTMLSelectElement;
    expect(select.value).toBe("");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).not.toHaveProperty("country");
  });
});

/**
 * The country's document preset (names, numbering, print layout) is offered
 * on the setup screen itself, for an organization that runs the warehouse
 * module, instead of waiting in Settings → document profile.
 */
describe("OnboardingPage — the country's document preset", () => {
  const warehouseProfile = {
    id: "equipment_wms",
    name: "Equipment & Warehouse",
    description: "d",
    default_modules: ["items", "warehouse"],
  };

  function useOffer(preset: string | null) {
    const seen: { body: { use_country_preset?: boolean } | null } = {
      body: null,
    };
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(onePage([warehouseProfile, profiles[0]])),
      ),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.get("*/api/v1/onboarding/country-preset", () =>
        HttpResponse.json({ preset }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        seen.body = (await request.json()) as {
          use_country_preset?: boolean;
        };
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );
    return seen;
  }

  afterEach(() => vi.restoreAllMocks());

  it("offers it ticked for a warehouse mode and sends the answer", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    const seen = useOffer("DE Lager");

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Equipment & Warehouse/i }),
    );
    const offer = await screen.findByRole("checkbox", {
      name: /document names and numbering/i,
    });
    expect(offer).toBeChecked();
    await userEvent.click(offer);
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).toMatchObject({ use_country_preset: false });
  });

  it("sends the accepted offer", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    const seen = useOffer("DE Lager");

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Equipment & Warehouse/i }),
    );
    await screen.findByRole("checkbox", {
      name: /document names and numbering/i,
    });
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).toMatchObject({ use_country_preset: true });
  });

  it("is not offered to a mode without the warehouse module", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    const seen = useOffer("DE Lager");

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await finishSetup();

    await waitFor(() => expect(seen.body).not.toBeNull());
    expect(seen.body).not.toHaveProperty("use_country_preset");
  });

  it("is not offered for a country that has no preset", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("ja-JP");
    useOffer(null);

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Equipment & Warehouse/i }),
    );
    await screen.findByLabelText(/country/i);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });
});

/**
 * The name is what invitations, outgoing mail and printed documents carry,
 * and registration only guessed one from the founder's own name.
 */
describe("OnboardingPage — the organization's name", () => {
  it("offers the registered name and sends the one the reader typed", async () => {
    let body: { organization_name?: string } | null = null;
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "org-1",
          name: "Jan Kowalski's Organization",
          onboarding_completed: false,
        }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        body = (await request.json()) as { organization_name?: string };
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );

    renderAt("/onboarding");

    const field = (await screen.findByLabelText(
      /organization name/i,
    )) as HTMLInputElement;
    await waitFor(() =>
      expect(field.value).toBe("Jan Kowalski's Organization"),
    );
    await userEvent.clear(field);
    await userEvent.type(field, "Kowalski Bakery");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({ organization_name: "Kowalski Bakery" });
  });
});

/**
 * The zone decides when a day starts — expiry dates, inventory periods,
 * reports — and a new organization used to be put on UTC whatever its
 * browser said, with nothing on the path saying so. There is no picker here
 * to prove, only that the browser's own answer travels with the setup.
 */
describe("OnboardingPage — the browser's time zone reaches the request", () => {
  it("sends the zone the setup screen runs in", async () => {
    let body: { timezone?: string } | null = null;
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        body = (await request.json()) as { timezone?: string };
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );

    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await finishSetup();

    await waitFor(() => expect(body).not.toBeNull());
    expect(body).toMatchObject({
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
  });
});

/**
 * The guess is only fair while the reader can change what it is guessed from,
 * and the first administrator of an installation is created speaking English.
 */
describe("OnboardingPage — a way off the first screen", () => {
  it("carries the language selector and a way to sign out", async () => {
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    renderAt("/onboarding");

    expect(
      await screen.findByRole("button", { name: /sign out/i }),
    ).toBeInTheDocument();
    // The selector shows the current language as its trigger label.
    expect(
      screen.getByRole("button", { name: /^EN, Language: English$/ }),
    ).toBeInTheDocument();
  });
});

/**
 * Production, API keys and webhooks belong to no profile, so the
 * first move of the people who need them used to be "go into Settings and
 * turn it on yourself". The second step is where a mode stops being a
 * verdict and becomes a starting point.
 */
describe("OnboardingPage — the second step decides what the mode starts with", () => {
  const modeProfiles = [
    {
      id: "food_home",
      name: "Food & Home",
      description: "d",
      default_modules: ["items", "recipes"],
      suggested_modules: ["maker"],
    },
  ];

  const catalogue = [
    {
      name: "items",
      display_name: "Inventory",
      description: "The things you have",
      icon: "Box",
      is_always_on: true,
    },
    {
      name: "recipes",
      display_name: "Recipes",
      description: "Cook from what you have",
      icon: "ChefHat",
      is_always_on: false,
    },
    {
      name: "maker",
      display_name: "Production",
      description: "Turn components into a finished thing",
      icon: "Hammer",
      is_always_on: false,
    },
  ];

  function mockCatalogue(
    onSetup?: (body: unknown) => void,
    enabledModules?: string[],
  ) {
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(onePage(modeProfiles)),
      ),
      http.get("*/api/v1/modules/available", () =>
        HttpResponse.json(onePage(catalogue)),
      ),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.get("*/api/v1/modules/my", () =>
        HttpResponse.json(enabledModules ?? ["items"]),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        onSetup?.(await request.json());
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );
  }

  it("offers what the mode does not enable, and pins what cannot be changed", async () => {
    mockCatalogue();
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    // What the mode enables arrives ticked; what it merely offers does not.
    expect(await screen.findByLabelText(/Recipes/)).toBeChecked();
    expect(screen.getByLabelText(/Production/)).not.toBeChecked();

    // A checkbox that cannot be unticked is a row asking for a decision it
    // will not accept, so the always-on modules are not rendered at all.
    expect(screen.queryByLabelText(/Inventory/)).not.toBeInTheDocument();
  });

  it("says the modules could not be loaded instead of showing an empty step", async () => {
    mockCatalogue();
    server.use(
      http.get(
        "*/api/v1/modules/available",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Recipes/)).not.toBeInTheDocument();
  });

  it("lists the modules once the reader retries a failed load", async () => {
    mockCatalogue();
    let calls = 0;
    server.use(
      http.get("*/api/v1/modules/available", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage(catalogue));
      }),
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await userEvent.click(
      await screen.findByRole("button", { name: /try again|retry/i }),
    );

    expect(await screen.findByLabelText(/Recipes/)).toBeChecked();
    expect(calls).toBe(2);
  });

  it("does not offer the modes while the enabled modules are unknown", async () => {
    mockCatalogue();
    server.use(
      http.get(
        "*/api/v1/modules/my",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderAt("/onboarding");

    // Ticking from a guess would switch off a module already running.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Food & Home/i }),
    ).not.toBeInTheDocument();
  });

  it("sends what the reader ticked and unticked", async () => {
    let body: unknown = null;
    mockCatalogue((received) => {
      body = received;
    });
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    await userEvent.click(await screen.findByLabelText(/Recipes/));
    await userEvent.click(screen.getByLabelText(/Production/));
    await userEvent.click(screen.getByRole("button", { name: /get started/i }));

    await waitFor(() => expect(body).not.toBeNull());
    const sent = body as { modules: string[] };
    expect(sent.modules).toContain("maker");
    expect(sent.modules).not.toContain("recipes");
  });

  it("shows a module the organization already switched on as ticked, and keeps it unless unticked", async () => {
    // Enabled through the API before the wizard was finished: the step used
    // to open from the profile alone, so the box read unticked and pressing
    // "Get started" switched off what the organization had just turned on.
    let body: unknown = null;
    mockCatalogue(
      (received) => {
        body = received;
      },
      ["items", "maker"],
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));

    expect(await screen.findByLabelText(/Production/)).toBeChecked();

    await userEvent.click(screen.getByRole("button", { name: /get started/i }));

    await waitFor(() => expect(body).not.toBeNull());
    expect((body as { modules: string[] }).modules).toContain("maker");
  });

  it("lets the reader go back and change the mode", async () => {
    mockCatalogue();
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    await userEvent.click(screen.getByRole("button", { name: /continue/i }));
    await screen.findByLabelText(/Production/);

    await userEvent.click(screen.getByRole("button", { name: /back/i }));

    expect(
      await screen.findByRole("button", { name: /Food & Home/i }),
    ).toBeInTheDocument();
  });
});

/**
 * The same leak the profile cards had, one screen later: the wizard
 * translated its own headings and rendered the module rows — the only
 * content this decision rests on — straight from the English manifest.
 */
describe("OnboardingPage — the offered modules speak the user's language", () => {
  it("names the modules in Polish, with no English manifest text left", async () => {
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(
          onePage([
            {
              id: "food_home",
              name: "Food & Home",
              description: "d",
              default_modules: ["recipes"],
              suggested_modules: ["maker"],
            },
          ]),
        ),
      ),
      http.get("*/api/v1/modules/available", () =>
        HttpResponse.json(
          onePage([
            {
              name: "recipes",
              display_name: "Recipes",
              description: "Cook from what you have",
              icon: "ChefHat",
              is_always_on: false,
            },
            {
              name: "maker",
              display_name: "Production",
              description: "Production runs, bills of materials (BOM).",
              icon: "Hammer",
              is_always_on: false,
            },
          ]),
        ),
      ),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    await withLanguage("pl", async () => {
      const { unmount } = renderAt("/onboarding");
      await userEvent.click(
        await screen.findByRole("button", { name: /Dom i jedzenie/ }),
      );
      await userEvent.click(screen.getByRole("button", { name: /Dalej/ }));

      expect(await screen.findByText("Produkcja")).toBeInTheDocument();
      expect(screen.queryByText("Production")).not.toBeInTheDocument();
      unmount();
    });
  });
});

/**
 * The household answer to "what should it start with?" is "do not ask me".
 * Someone who came to know what is in the fridge and what they can cook gets
 * a working application without a single question about modules; an advanced
 * self-hoster who wants API keys will find them in the store.
 */
describe("OnboardingPage — a mode that offers nothing asks nothing", () => {
  it("applies the household mode without a second step", async () => {
    let body: unknown = null;
    server.use(
      http.get("*/api/v1/profiles", () =>
        HttpResponse.json(
          onePage([
            {
              id: "food_home",
              name: "Food & Home",
              description: "d",
              default_modules: ["recipes"],
              suggested_modules: [],
            },
          ]),
        ),
      ),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.post("*/api/v1/onboarding/setup", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: "org-1", onboarding_completed: true });
      }),
    );

    renderAt("/onboarding");
    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );

    // No "Continue" — the first button is the last one.
    expect(
      screen.queryByRole("button", { name: /continue/i }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /get started/i }));

    // A step nobody saw must not speak for them: an untouched `[]` would read
    // as "they unticked everything" and strip the mode down to the pinned set.
    await waitFor(() => expect(body).not.toBeNull());
    expect((body as { modules?: string[] }).modules).toBeUndefined();
  });
});

/**
 * The wizard is the first run of an organization, not a setting. A completed
 * organization used to be shown it anyway (a submit answered 409), a reader
 * who may not set anything up was offered it, and a failed profile list left
 * the one card that needs no profile as the only choice, with no message.
 */
describe("OnboardingPage — only while there is something to set up", () => {
  const asUser = (role: string) =>
    useAuthStore.setState({
      user: { id: "1", role, is_superuser: false, permissions: [] } as never,
      isAuthenticated: true,
    });

  afterEach(() => {
    cleanup();
    useAuthStore.setState({ user: null });
  });

  it("sends a completed organization on instead of showing the wizard", async () => {
    asUser("admin");
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: true }),
      ),
    );

    renderAt("/onboarding");

    expect(await screen.findByText("HOME_REACHED")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Food & Home/i }),
    ).not.toBeInTheDocument();
  });

  it("tells a non-administrator it is not theirs to set up, without the wizard", async () => {
    asUser("viewer");
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    const { qc } = renderAt("/onboarding");

    expect(
      await screen.findByText(/only an administrator can set this up/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Food & Home/i }),
    ).not.toBeInTheDocument();
    // Let the queries behind the screen land inside the test.
    await waitFor(() => expect(qc.isFetching()).toBe(0));
  });

  it("says the profiles could not be loaded instead of offering one card", async () => {
    asUser("admin");
    server.use(
      http.get(
        "*/api/v1/profiles",
        () => new HttpResponse(null, { status: 500 }),
      ),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );

    const { qc } = renderAt("/onboarding");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await waitFor(() => expect(qc.isFetching()).toBe(0));
    expect(
      screen.getByRole("button", { name: /try again|retry/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /just one module/i }),
    ).not.toBeInTheDocument();
  });
});

describe("OnboardingPage — recovering and leaving", () => {
  const asAdmin = () =>
    useAuthStore.setState({
      user: {
        id: "1",
        role: "admin",
        is_superuser: false,
        permissions: [],
      } as never,
      isAuthenticated: true,
    });
  const originalLogout = useAuthStore.getState().logout;

  afterEach(() => {
    cleanup();
    useAuthStore.setState({ user: null, logout: originalLogout });
  });

  it("offers the modes once the reader retries a failed profile list", async () => {
    asAdmin();
    let calls = 0;
    server.use(
      http.get("*/api/v1/profiles", () => {
        calls += 1;
        return calls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(onePage(profiles));
      }),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /try again|retry/i }),
    );

    expect(
      await screen.findByRole("button", { name: /Food & Home/i }),
    ).toBeInTheDocument();
  });

  it("re-reads the enabled modules, not only the profiles, when that is what failed", async () => {
    asAdmin();
    let moduleCalls = 0;
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
      http.get("*/api/v1/modules/my", () => {
        moduleCalls += 1;
        return moduleCalls === 1
          ? new HttpResponse(null, { status: 500 })
          : HttpResponse.json(["items"]);
      }),
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /try again|retry/i }),
    );

    expect(
      await screen.findByRole("button", { name: /Food & Home/i }),
    ).toBeInTheDocument();
    expect(moduleCalls).toBe(2);
  });

  it("signs out from the header while a mode is still to be picked", async () => {
    asAdmin();
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ logout });
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /sign out/i }),
    );

    expect(logout).toHaveBeenCalledTimes(1);
  });

  it("signs out from the screen that says setup is not theirs to do", async () => {
    useAuthStore.setState({
      user: {
        id: "2",
        role: "viewer",
        is_superuser: false,
        permissions: [],
      } as never,
      isAuthenticated: true,
    });
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({ logout });
    server.use(
      http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
      http.get("*/api/v1/organizations/my", () =>
        HttpResponse.json({ id: "org-1", onboarding_completed: false }),
      ),
    );
    const { qc } = renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /sign out/i }),
    );

    expect(logout).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(qc.isFetching()).toBe(0));
  });
});

function serveFirstRun(name = "Anna Owner's Organization") {
  server.use(
    http.get("*/api/v1/profiles", () => HttpResponse.json(onePage(profiles))),
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", name, onboarding_completed: false }),
    ),
  );
}

/** The currency and the country come from one guess, not two. */
describe("OnboardingPage — the country follows the interface language too", () => {
  afterEach(() => vi.restoreAllMocks());

  it("opens a Polish interface on PL even when the browser says en-US", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("en-US");
    serveFirstRun();

    await withLanguage("pl", async () => {
      const { unmount } = renderAt("/onboarding");
      const country = (await screen.findByLabelText(
        /kraj/i,
      )) as HTMLSelectElement;
      const currency = screen.getByLabelText(/waluta/i) as HTMLSelectElement;
      expect(currency.value).toBe("PLN");
      expect(country.value).toBe("PL");
      unmount();
    });
  });
});

/** A language the table has no row for takes both answers from the browser. */
describe("OnboardingPage — the currency follows the country it came with", () => {
  afterEach(() => vi.restoreAllMocks());

  it("offers EUR with DE for an English interface on a de-DE browser", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("de-DE");
    serveFirstRun();

    renderAt("/onboarding");
    const country = (await screen.findByLabelText(
      /country/i,
    )) as HTMLSelectElement;
    const currency = screen.getByLabelText(/currency/i) as HTMLSelectElement;
    expect(country.value).toBe("DE");
    expect(currency.value).toBe("EUR");
  });

  it("offers BRL with BR for an English interface on a pt-BR browser", async () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("pt-BR");
    serveFirstRun();

    renderAt("/onboarding");
    const country = (await screen.findByLabelText(
      /country/i,
    )) as HTMLSelectElement;
    const currency = screen.getByLabelText(/currency/i) as HTMLSelectElement;
    expect(country.value).toBe("BR");
    expect(currency.value).toBe("BRL");
  });
});

/** The profile cards say which one is chosen to assistive technology. */
describe("OnboardingPage — the chosen card is announced", () => {
  it("marks the picked profile card pressed and the others not", async () => {
    serveFirstRun();
    renderAt("/onboarding");

    const food = await screen.findByRole("button", { name: /Food & Home/i });
    const equipment = screen.getByRole("button", {
      name: /Equipment & Warehouse/i,
    });
    expect(food).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(food);
    expect(food).toHaveAttribute("aria-pressed", "true");
    expect(equipment).toHaveAttribute("aria-pressed", "false");
  });
});

/** An emptied name is refused, not silently replaced by a guessed one. */
describe("OnboardingPage — the organization name", () => {
  it("says so and holds the button while the name is empty", async () => {
    serveFirstRun();
    renderAt("/onboarding");

    await userEvent.click(
      await screen.findByRole("button", { name: /Food & Home/i }),
    );
    const name = await screen.findByLabelText(/organization name/i);
    await waitFor(() => expect(name).toHaveValue("Anna Owner's Organization"));
    const go = screen.getByRole("button", { name: /continue|get started/i });
    expect(go).toBeEnabled();

    await userEvent.clear(name);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /give the organization a name/i,
    );
    expect(go).toBeDisabled();

    await userEvent.type(name, "Northwind");
    expect(go).toBeEnabled();
  });
});
