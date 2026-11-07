import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AppStore from "@/modules/settings/components/AppStore";
import RolesPage from "@/modules/settings/components/roles/RolesPage";
import ApiKeysPage from "@/modules/api_keys/pages/ApiKeysPage";
import WebhooksPage from "@/modules/webhooks/pages/WebhooksPage";
import AiConnectionsTab from "@/modules/settings/components/ai/AiConnectionsTab";
import { WorkspaceModeSettings } from "@/modules/settings/components/WorkspaceModeSettings";
import SettingsEmailTab from "@/modules/settings/components/SettingsEmailTab";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["webhooks", "api_keys"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * The shell was the fifth area with this class, after equipment, trade and
 * the kitchen — and the two worst instances in the whole pass are here.
 *
 * `/settings/email` answered a failed read with "EMAIL CONFIGURATION: NOT
 * CONFIGURED", which is not a blank space but a claim, and a false one: an
 * administrator whose invitations had stopped would read that SMTP was never
 * set up and type a mail server over the working one. `/apps` answered with
 * "0 of the 0 modules offered here are switched on" — the same sentence that
 * says "11 of the 15" when the catalogue arrives, so it reads as a fact about
 * the installation rather than as silence.
 *
 * The remaining five each invited the reader to create the first of something
 * there were already several of. The fix is the one the other three areas
 * took: `QueryFailure`, which separates "nothing here" from "could not read"
 * from "not allowed", and withholds the retry button on a refusal.
 */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.subtitle ? (
        <div data-testid="header-subtitle">{data.subtitle}</div>
      ) : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderAt(path: string, element: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderHost>
          <Routes>
            <Route path={path} element={element} />
          </Routes>
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** An administrator: every one of these screens is admin-gated in the shell. */
const ACCOUNT = [
  "admin:access",
  "org:read",
  "org:settings:write",
  "org:members:write",
  "system:config:write",
  "webhooks:read",
  "webhooks:write",
  "api_keys:read",
  "api_keys:write",
];

const answers = (path: string, status: number) =>
  http.get(path, () => new HttpResponse(null, { status }));

interface Surface {
  name: string;
  path: string;
  element: React.ReactNode;
  /** The endpoint whose failure the pass observed. */
  endpoint: string;
  /** What that endpoint returns when there is genuinely nothing. */
  emptyBody: object;
  /** Something only the empty — or wrongly-computed — state renders. */
  emptyText: RegExp;
}

const SURFACES: Surface[] = [
  {
    name: "the app store",
    path: "/apps",
    element: <AppStore />,
    endpoint: "/api/v1/modules/available",
    emptyBody: onePage([]),
    // The count is the claim: "0 of the 0 modules offered here…".
    emptyText: /0 of the 0/i,
  },
  {
    name: "roles",
    path: "/settings/roles",
    element: <RolesPage />,
    endpoint: "/api/v1/roles",
    emptyBody: onePage([]),
    emptyText: /no custom roles yet/i,
  },
  {
    name: "API keys",
    path: "/settings/api-keys",
    element: <ApiKeysPage />,
    endpoint: "/api/v1/api-keys",
    emptyBody: onePage([]),
    emptyText: /no api keys/i,
  },
  {
    name: "webhooks",
    path: "/settings/webhooks",
    element: <WebhooksPage />,
    endpoint: "/api/v1/webhooks/endpoints",
    emptyBody: onePage([]),
    emptyText: /no webhooks configured/i,
  },
  {
    name: "AI connections",
    path: "/settings/ai",
    element: <AiConnectionsTab />,
    endpoint: "/api/v1/ai-connections",
    emptyBody: onePage([]),
    emptyText: /no connections yet/i,
  },
  {
    name: "my modules",
    path: "/settings/my-modules",
    element: <WorkspaceModeSettings />,
    endpoint: "/api/v1/profiles",
    emptyBody: onePage([]),
    emptyText: /no workspace modes available/i,
  },
  {
    name: "the mail server",
    path: "/settings/email",
    element: <SettingsEmailTab />,
    endpoint: "/api/v1/organizations/my",
    // An organization that really has no SMTP block of its own and no
    // installation-wide server behind it: the badge is then telling the truth.
    emptyBody: { id: "org-1", name: "QA", settings: {}, can_send_email: false },
    emptyText: /not configured/i,
  },
];

beforeEach(() => {
  server.resetHandlers();
  server.use(
    http.get("/api/v1/modules/available", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/modules/my", () => HttpResponse.json([])),
    http.get("/api/v1/roles", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/roles/permission-catalog", () =>
      HttpResponse.json({ system: [], modules: [] }),
    ),
    http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/api-keys/capabilities", () =>
      HttpResponse.json({
        catalog: [],
        grantable: ["items:read"],
        default_permissions: ["items:read"],
        withheld_permissions: ["org:settings:write"],
        admin_areas_blocked: true,
        header: "X-API-Key",
        scopes: [],
      }),
    ),
    http.get("/api/v1/webhooks/endpoints", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/webhooks/events", () => HttpResponse.json([])),
    http.get("/api/v1/ai-connections", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/ai-connections/purposes", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/profiles", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({
        id: "org-1",
        name: "QA",
        settings: {},
        can_send_email: false,
      }),
    ),
  );
  signInWith(ACCOUNT);
});

afterEach(() => {
  signOut();
});

describe.each(SURFACES)(
  "Shell — $name says which of the three happened",
  ({ path, element, endpoint, emptyBody, emptyText }) => {
    it("shows the empty state when the read succeeds and there is nothing", async () => {
      server.use(http.get(endpoint, () => HttpResponse.json(emptyBody)));
      renderAt(path, element);

      expect(await screen.findByText(emptyText)).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });

    it("offers a retry, not a claim about the installation, when the read fails", async () => {
      server.use(answers(endpoint, 500));
      renderAt(path, element);

      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(
        await screen.findByRole("button", { name: /try again|retry/i }),
      ).toBeInTheDocument();
      expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
    });

    it("says the account has no access, with no retry, when the read is refused", async () => {
      server.use(answers(endpoint, 403));
      renderAt(path, element);

      expect(
        await screen.findByText(/you do not have access to this/i),
      ).toBeInTheDocument();
      expect(screen.queryByText(emptyText)).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /try again|retry/i }),
      ).not.toBeInTheDocument();
    });
  },
);

describe("Shell — the two that made a claim rather than leaving a blank", () => {
  it("withholds the mail-server form as well as the badge when the read fails", async () => {
    server.use(answers("/api/v1/organizations/my", 500));
    renderAt("/settings/email", <SettingsEmailTab />);

    await screen.findByRole("alert");
    // Blank fields over a working SMTP block are the same trap as the badge:
    // whatever is typed into them is what Save would send.
    expect(
      screen.queryByRole("button", { name: /smtp|mail server/i }),
    ).not.toBeInTheDocument();
  });

  it("withholds the module count when the catalogue could not be read", async () => {
    server.use(answers("/api/v1/modules/available", 500));
    renderAt("/apps", <AppStore />);

    await screen.findByRole("alert");
    // The title stays — the reader still knows where they are.
    expect(screen.getByText(/app store|modules/i)).toBeInTheDocument();
    expect(screen.queryByText(/0 of the 0/i)).not.toBeInTheDocument();
  });
});
