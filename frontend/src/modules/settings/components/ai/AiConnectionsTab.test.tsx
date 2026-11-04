import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AxiosError, type AxiosResponse } from "axios";

import AiConnectionsTab from "@/modules/settings/components/ai/AiConnectionsTab";
import { MemoryRouter } from "react-router-dom";
import { ModulesProvider } from "@/contexts/ModulesContext";
import type { AiConnection, AiPurpose } from "@/types/ai";

const purposesFailure = vi.hoisted(() => ({ failed: false }));
// An organization with no connection of its own, on a server whose default
// model serves one purpose (or none).
const noConnections = vi.hoisted(() => ({
  on: false,
  serverDefault: false,
}));
// Modules the organization has switched on (the real provider would ask the
// API; an unauthenticated test provider knows none).
const enabled = vi.hoisted(() => ({ modules: ["vision"] as string[] }));
const mutateCreate = vi.fn();
const mutateDelete = vi.fn();

const connections: AiConnection[] = [
  {
    id: "conn-1",
    name: "Vision pool",
    provider: "openrouter",
    api_key: "**********",
    api_base_url: "",
    model_name: "google/gemini-2.0-flash",
    temperature: null,
    max_tokens: null,
    top_p: null,
    capabilities: ["vision"],
    capability_checks: {},
    created_at: "",
    updated_at: "",
  },
];

const purposes: AiPurpose[] = [
  {
    key: "vision.extract",
    label_key: "vision:ai.purposeLabel",
    description_key: "vision:ai.purposeDesc",
    owner_module: "vision",
    capability: "vision",
    bound_connection_id: "conn-1",
    usable: true,
  },
];

vi.mock("@/modules/settings/hooks/useAiConnections", () => ({
  useAiConnections: () => ({
    data: noConnections.on ? [] : connections,
    isLoading: false,
  }),
  useAiPurposes: () =>
    purposesFailure.failed
      ? {
          data: undefined,
          isError: true,
          error: new Error("boom"),
          refetch: vi.fn(),
        }
      : {
          data: noConnections.on
            ? [
                {
                  ...purposes[0],
                  bound_connection_id: null,
                  usable: noConnections.serverDefault,
                },
              ]
            : purposes,
          isLoading: false,
        },
  useCreateAiConnection: () => ({
    mutate: mutateCreate,
    isPending: false,
  }),
  useUpdateAiConnection: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
  useDeleteAiConnection: () => ({
    mutate: mutateDelete,
    isPending: false,
  }),
  useSetAiBinding: () => ({ mutate: vi.fn(), isPending: false }),
  useTestAiConnection: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({ enabledModules: enabled.modules }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useOrganization: () => ({ data: { settings: {} }, isLoading: false }),
  useUpdateOrganization: () => ({ mutate: vi.fn(), isPending: false }),
}));

function renderTab() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ModulesProvider>
          <AiConnectionsTab />
        </ModulesProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("AiConnectionsTab", () => {
  it("says the purposes could not be loaded instead of hiding the bindings", async () => {
    purposesFailure.failed = true;
    try {
      renderTab();
      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /try again/i }),
      ).toBeInTheDocument();
    } finally {
      purposesFailure.failed = false;
    }
  });

  it("does not claim AI needs a connection while the server default serves a purpose", async () => {
    noConnections.on = true;
    noConnections.serverDefault = true;
    try {
      renderTab();
      expect(
        await screen.findByText(/already run on the server's default model/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Add a connection to start using AI/i),
      ).toBeNull();
    } finally {
      noConnections.on = false;
      noConnections.serverDefault = false;
    }
  });

  it("keeps asking for a connection when the served purpose's module is off", async () => {
    noConnections.on = true;
    noConnections.serverDefault = true;
    enabled.modules = [];
    try {
      renderTab();
      expect(
        await screen.findByText(/Add a connection to start using AI/i),
      ).toBeInTheDocument();
      expect(screen.queryByText(/already run on the server/i)).toBeNull();
    } finally {
      noConnections.on = false;
      noConnections.serverDefault = false;
      enabled.modules = ["vision"];
    }
  });

  it("keeps asking for a first connection when nothing serves any purpose", async () => {
    noConnections.on = true;
    try {
      renderTab();
      expect(
        await screen.findByText(/Add a connection to start using AI/i),
      ).toBeInTheDocument();
    } finally {
      noConnections.on = false;
    }
  });

  it("renders list of connection cards", async () => {
    renderTab();
    expect(await screen.findAllByText(/Vision pool/i)).not.toHaveLength(0);
    expect(screen.getByText("Vision")).toBeInTheDocument();
  });

  it("leaves the page's name to the shell heading and keeps one level per section", async () => {
    // The card title used to repeat the shell h1's exact words as an h2, and
    // the bindings section sat an h3 below it — the same name twice in the
    // heading tree, one level skipped.
    renderTab();
    await screen.findAllByText(/Vision pool/i);

    expect(
      screen.queryByRole("heading", { name: "AI Connections" }),
    ).toBeNull();
    // Not as plain text either: that was the same name a second time.
    expect(screen.queryByText("AI Connections")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Default per purpose", level: 2 }),
    ).toBeInTheDocument();
  });

  it("opens modal on Add connection click", async () => {
    renderTab();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Add connection/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Add connection/i }),
      ).toBeInTheDocument();
    });
  });

  it("closes modal on cancel", async () => {
    renderTab();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Add connection/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Add connection/i }),
      ).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Cancel/i }));
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: /Add connection/i }),
      ).toBeNull();
    });
  });

  it("refuses delete when connection is bound to a purpose", async () => {
    renderTab();
    const user = userEvent.setup();

    const deleteBtn = screen.getByRole("button", {
      name: /Delete connection/i,
    });
    await user.click(deleteBtn);

    expect(mutateDelete).not.toHaveBeenCalled();
  });
});

describe("AiConnectionsTab — the modal opens ready to work", () => {
  /**
   * The dialog opened with a provider already chosen and its two required
   * fields empty: the defaults were applied by the provider-change handler
   * and by nothing else. The shortest path — open it, accept the provider
   * that is already selected, type the key — was the one path that could
   * not work: the backend answered "AI connection base URL must use http
   * or https".
   */
  it("fills the base URL and model of the provider shown on open", async () => {
    renderTab();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Add connection/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Add connection/i }),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByDisplayValue("https://openrouter.ai/api/v1"),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("google/gemini-2.0-flash-001"),
    ).toBeInTheDocument();
  });

  it("still replaces them when the reader picks another provider", async () => {
    renderTab();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Add connection/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Add connection/i }),
      ).toBeInTheDocument();
    });

    const providerSelect = screen.getByLabelText(/provider/i);
    await user.selectOptions(providerSelect, "anthropic");

    expect(
      screen.getByDisplayValue("https://api.anthropic.com"),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("claude-sonnet-4-5")).toBeInTheDocument();
  });
});

describe("AiConnectionsTab — the save refusal lands on the field", () => {
  /**
   * The backend refuses a draft without a base URL with a 422 whose loc
   * names the field. That refusal used to surface only as a vanishing
   * toast with the raw wire string; the name-required rule next to it
   * rendered red under its input. A server refusal with a field in its
   * loc now gets the same treatment — the sentence stands under the
   * field it is about.
   */
  it("shows the 422 refusal under the base URL input", async () => {
    const refusal =
      "This provider is reached over HTTP, so the base URL is required";
    mutateCreate.mockImplementation(
      (_draft: unknown, opts: { onError?: (error: unknown) => void }) => {
        opts?.onError?.(
          new AxiosError(
            "Request failed with status code 422",
            undefined,
            undefined,
            null,
            {
              status: 422,
              data: {
                detail: [
                  {
                    loc: ["body", "api_base_url"],
                    msg: refusal,
                    type: "value_error",
                  },
                ],
              },
            } as unknown as AxiosResponse,
          ),
        );
      },
    );

    renderTab();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Add connection/i }));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /Add connection/i }),
      ).toBeInTheDocument();
    });

    await user.type(
      screen.getByLabelText(/name/i),
      "Pool the server will refuse",
    );
    await user.clear(screen.getByLabelText(/base url/i));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    const line = await screen.findByText(refusal);
    expect(line).toBeInTheDocument();
    const input = screen.getByLabelText(/base url/i);
    expect(input).toHaveAttribute("aria-invalid", "true");
  });
});
