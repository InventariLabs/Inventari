import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render as renderWithProviders,
  screen,
  within,
  waitFor,
} from "@/test/utils";
import userEvent from "@testing-library/user-event";

import { AiConnectionFields } from "@/modules/settings/components/ai/AiConnectionFields";
import { aiConnectionsApi } from "@/lib/api/aiConnections";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { http, HttpResponse, type JsonBodyType } from "msw";
import {
  PROVIDERS,
  PROVIDER_GROUPS,
} from "@/modules/settings/components/ai/providers";
import type { AiConnectionDraft, AiConnectionTestResult } from "@/types/ai";

const toasts = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: toasts }));

const empty: AiConnectionDraft = {
  name: "",
  provider: "openrouter",
  api_key: null,
  api_base_url: null,
  model_name: null,
  temperature: null,
  max_tokens: null,
  top_p: null,
  capabilities: ["vision", "text"],
};

describe("AiConnectionFields", () => {
  it("offers the providers as a list of names, grouped by what they are", () => {
    // A grid of fifteen logo tiles filled the dialog before the first field
    // a person has to think about, and looked like nothing else that asks
    // this question. The control is the one the rest of the app uses.
    renderWithProviders(
      <AiConnectionFields value={empty} onChange={vi.fn()} />,
    );

    const select = screen.getByRole("combobox", { name: /provider/i });
    expect(
      within(select).getByRole("option", { name: "OpenAI" }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole("option", { name: "Custom OpenAI-compatible" }),
    ).toBeInTheDocument();
    expect(within(select).getAllByRole("option")).toHaveLength(
      PROVIDERS.length,
    );
    // Grouped, so a list of fifteen names is still readable.
    expect(select.querySelectorAll("optgroup").length).toBe(
      PROVIDER_GROUPS.length,
    );
  });

  it("asks which provider before asking anything about it", () => {
    // The provider decides what the rest of the form is, so it is the first
    // thing on it.
    renderWithProviders(
      <AiConnectionFields value={empty} onChange={vi.fn()} />,
    );

    const select = screen.getByRole("combobox", { name: /provider/i });
    const name = screen.getByPlaceholderText(/e\.g\.|storeroom|czujnik/i);
    expect(
      select.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("does not let the browser fill the connection's name with an address", () => {
    // "Name" read as a person's, and the field arrived holding an email
    // address nobody had typed into it.
    renderWithProviders(
      <AiConnectionFields value={empty} onChange={vi.fn()} />,
    );

    const name = screen.getByPlaceholderText(/e\.g\.|storeroom|czujnik/i);
    expect(name).toHaveAttribute("autocomplete", "off");
  });

  it("shows baseUrl for every provider except Google (SDK-based)", () => {
    const onChange = vi.fn();

    const { rerender } = renderWithProviders(
      <AiConnectionFields value={empty} onChange={onChange} />,
    );

    // OpenRouter (default) — base URL input IS visible now (showBaseUrl=true).
    expect(
      screen.getByPlaceholderText("https://api.example.com/v1"),
    ).toBeInTheDocument();

    // Switch to Google (native SDK, no configurable endpoint) — hidden.
    rerender(
      <AiConnectionFields
        value={{ ...empty, provider: "google" }}
        onChange={onChange}
      />,
    );
    expect(
      screen.queryByPlaceholderText("https://api.example.com/v1"),
    ).toBeNull();
  });

  it("fills in what the chosen provider needs", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <AiConnectionFields value={empty} onChange={onChange} />,
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: /provider/i }),
      "openai",
    );

    expect(onChange).toHaveBeenCalledTimes(1);
    const draft = onChange.mock.calls[0][0];
    expect(draft.provider).to.equal("openai");
    expect(draft.api_base_url).to.equal("https://api.openai.com/v1");
    expect(draft.model_name).to.equal("gpt-4o");
  });

  it("hands the provider's default back when the field is emptied", async () => {
    // An emptied base URL used to strand the connection: the save went
    // through and the first call died on a relative URL. The default comes
    // back when the field is left empty.
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { fireEvent } = await import("@/test/utils");

    const { rerender } = renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, api_base_url: "https://openrouter.ai/api/v1" }}
        onChange={onChange}
      />,
    );

    const baseUrl = screen.getByPlaceholderText("https://api.example.com/v1");
    await user.clear(baseUrl);
    // The dialog is a controlled component: the emptied draft comes back
    // down as the new value before the field loses focus.
    rerender(
      <AiConnectionFields
        value={{ ...empty, api_base_url: null }}
        onChange={onChange}
      />,
    );
    fireEvent.blur(baseUrl);

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ api_base_url: "https://openrouter.ai/api/v1" }),
    );
  });

  it("says where a key for the chosen provider comes from", () => {
    // The descriptor has always carried the address; nothing showed it.
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "openai" }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: /openai/i })).toHaveAttribute(
      "href",
      "https://platform.openai.com/api-keys",
    );
  });

  it("asks for a model only where there is one to name", () => {
    // The model input is present for every provider that serves models,
    // with a generic placeholder. The reader is a service, not a model —
    // its field used to render with another provider's placeholder, asking
    // a question the credential has no answer for.
    const onChange = vi.fn();
    const { rerender } = renderWithProviders(
      <AiConnectionFields value={empty} onChange={onChange} />,
    );
    expect(
      screen.getByPlaceholderText("google/gemini-2.0-flash-001"),
    ).toBeInTheDocument();

    rerender(
      <AiConnectionFields
        value={{ ...empty, provider: "jina" }}
        onChange={onChange}
      />,
    );
    expect(
      screen.queryByPlaceholderText("google/gemini-2.0-flash-001"),
    ).toBeNull();
  });

  it("lets the reader say the model does not read images", async () => {
    // The provider's suggestion used to be drawn as a fixed badge with a
    // tick. A protocol is not a model: a connection to a text-only model
    // through an OpenAI-compatible endpoint inherited VISION from the shape
    // of the API and could not be told otherwise, so it stayed on the list of
    // things to read photographs with.
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <AiConnectionFields
        value={{
          ...empty,
          provider: "openai",
          capabilities: ["vision", "text"],
        }}
        onChange={onChange}
      />,
    );

    const vision = screen.getByRole("checkbox", { name: /Vision/i });
    expect(vision).toBeEnabled();

    await user.click(vision);

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].capabilities).to.deep.equal(["text"]);
  });

  it("still offers the capability the provider leaves open", () => {
    // A local server is treated conservatively: text is assumed, vision is a
    // claim the reader makes about the model they loaded.
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "ollama" }}
        onChange={vi.fn()}
      />,
    );

    const vision = screen.getByRole("checkbox", { name: /Vision/i });
    expect(vision).toBeInTheDocument();
    expect(vision).toBeEnabled();
  });

  it("describes the chosen provider through the catalogs", () => {
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "ollama" }}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Local OpenAI-compatible server on port 11434."),
    ).toBeInTheDocument();
  });

  it("names the one entry that is not a brand in the reader's language", async () => {
    // Fourteen of the fifteen entries are brands and keep their name in every
    // language. The fifteenth says what it is for, and it stayed English on a
    // Polish screen — in a list whose group heading and description, four
    // lines away, were both Polish.
    await withLanguage("pl", async () => {
      renderWithProviders(
        <AiConnectionFields value={empty} onChange={vi.fn()} />,
      );

      const select = screen.getByRole("combobox", { name: "Dostawca" });
      expect(
        within(select).getByRole("option", {
          name: "Własny (zgodny z OpenAI)",
        }),
      ).toBeInTheDocument();
      expect(
        within(select).queryByRole("option", {
          name: "Custom OpenAI-compatible",
        }),
      ).not.toBeInTheDocument();
      // A brand is still its own name.
      expect(
        within(select).getByRole("option", { name: "OpenAI" }),
      ).toBeInTheDocument();
    });
  });

  it("hints at a key's shape for a custom endpoint, not at the field's label", () => {
    // The custom entry's key field read "API Key" — a label in English where
    // the three entries above it show what a key looks like.
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "custom" }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByPlaceholderText("sk-...")).toBeInTheDocument();
  });
});

describe("AiConnectionFields — what the connection test reports", () => {
  // A draft the test can be sent at all: the key, and — because OpenRouter is
  // reached over HTTP — an address. The form refuses a draft missing either
  // one before a request exists, and its own pins cover that below.
  const withKey: AiConnectionDraft = {
    ...empty,
    api_key: "sk-test",
    api_base_url: "https://openrouter.ai/api/v1",
  };

  const result = (
    overrides: Partial<AiConnectionTestResult> = {},
  ): AiConnectionTestResult => ({
    ok: true,
    verdict: "ok",
    models: ["a/model", "b/model"],
    contract: {
      checked: true,
      ok: true,
      purpose: "vision.extract",
      attempts: 1,
      schema_enforced: false,
    },
    ...overrides,
  });

  const clickTest = async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AiConnectionFields value={withKey} onChange={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /Test connection/i }));
  };

  beforeEach(() => {
    toasts.success.mockClear();
    toasts.error.mockClear();
    toasts.warning.mockClear();
  });

  it("says the model did the job, not merely that the key works", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(result());

    await clickTest();

    expect(toasts.success).toHaveBeenCalledWith(
      expect.stringContaining("read the sample label"),
    );
  });

  it("says the reader fetched a page, not that a model read a label", async () => {
    // The reader's test reads one page; the shared sentences below report
    // "0 models available" and "the model read the sample label" for it.
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        models: [],
        contract: {
          checked: true,
          ok: true,
          purpose: "recipes.url_fetch",
          schema_enforced: false,
        },
      }),
    );

    await clickTest();

    expect(toasts.success).toHaveBeenCalledWith(
      expect.stringContaining("fetched a test page"),
    );
    expect(toasts.success).not.toHaveBeenCalledWith(
      expect.stringContaining("sample label"),
    );
  });

  it("says a keyless reader runs on the free tier instead of counting models", async () => {
    // No key is a legal state for the reader — the shared free tier — and
    // "Credentials work — 0 models available" answers a question nobody
    // asked about a connection that was never billed per model.
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        verdict: "unchecked",
        models: [],
        contract: {
          checked: false,
          ok: false,
          purpose: "recipes.url_fetch",
          reason: "no_key_free_tier",
          schema_enforced: false,
        },
      }),
    );

    await clickTest();

    expect(toasts.warning).toHaveBeenCalledWith(
      expect.stringContaining("free tier"),
    );
    expect(toasts.warning).not.toHaveBeenCalledWith(
      expect.stringContaining("models available"),
    );
  });

  it("warns that the shape was not enforced on the wire", async () => {
    // A pass earned by the parser is not the same as a pass the provider
    // guaranteed, and the difference shows up later, in the field.
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(result());

    await clickTest();

    expect(toasts.warning).toHaveBeenCalledWith(
      expect.stringContaining("does not enforce"),
    );
  });

  it("does not warn when the provider did enforce the shape", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        contract: {
          checked: true,
          ok: true,
          purpose: "vision.extract",
          attempts: 1,
          schema_enforced: true,
        },
      }),
    );

    await clickTest();

    expect(toasts.warning).not.toHaveBeenCalled();
  });

  it("warns beside the address that a local engine needs the guard opened", async () => {
    // The form fills in host.docker.internal for a local provider and the
    // backend then refuses it — the one default the application hands out and
    // will not accept. Saying so here is cheaper than a failed save.
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "ollama" }}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/LLM_ALLOW_PRIVATE_NETWORKS=true/),
    ).toBeInTheDocument();
  });

  it("does not show that hint for a cloud provider", async () => {
    renderWithProviders(
      <AiConnectionFields
        value={{ ...empty, provider: "openrouter" }}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.queryByText(/LLM_ALLOW_PRIVATE_NETWORKS=true/),
    ).not.toBeInTheDocument();
  });

  it("says how much of the sample label the model actually read", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        contract: {
          checked: true,
          ok: true,
          purpose: "vision.extract",
          attempts: 1,
          schema_enforced: true,
          reading: {
            fields: {
              name: { expected: "OAT DRINK", read: "Oat Drink", matches: true },
            },
            matched: 3,
            of: 3,
          },
        },
      }),
    );

    await clickTest();

    expect(toasts.success).toHaveBeenCalledWith(
      expect.stringContaining("read all 3 fields"),
    );
  });

  it("warns when the shape was right and the reading was not", async () => {
    // The contract holds, so the verdict stays green — but a model that read
    // nothing off the label is still the wrong model, and Settings is where
    // that has to show, not the user's first product.
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        contract: {
          checked: true,
          ok: true,
          purpose: "vision.extract",
          attempts: 1,
          schema_enforced: true,
          reading: {
            fields: {
              name: { expected: "OAT DRINK", read: "Milk", matches: false },
            },
            matched: 0,
            of: 3,
          },
        },
      }),
    );

    await clickTest();

    expect(toasts.success).not.toHaveBeenCalled();
    expect(toasts.warning).toHaveBeenCalledWith(
      expect.stringContaining("only 0 of 3"),
    );
  });

  it("reports an off-contract answer as a failure, with what was returned", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        verdict: "contract_failed",
        contract: {
          checked: true,
          ok: false,
          purpose: "vision.extract",
          attempts: 2,
          schema_enforced: false,
          answer_preview: "I cannot make out the printed text.",
        },
      }),
    );

    await clickTest();

    expect(toasts.error).toHaveBeenCalledWith(
      expect.stringContaining("I cannot make out the printed text."),
    );
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it("truncates a rambling refusal instead of pasting it into the toast", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        verdict: "contract_failed",
        contract: {
          checked: true,
          ok: false,
          purpose: "vision.extract",
          attempts: 2,
          schema_enforced: false,
          answer_preview: "I am unable to comply. ".repeat(40),
        },
      }),
    );

    await clickTest();

    const message = toasts.error.mock.calls[0][0] as string;
    expect(message.length).toBeLessThan(400);
    expect(message).toContain("…");
  });

  it("does not claim a pass it never checked", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockResolvedValue(
      result({
        verdict: "unchecked",
        contract: {
          checked: false,
          ok: false,
          purpose: null,
          schema_enforced: false,
          reason: "no_probe_for_capabilities",
        },
      }),
    );

    await clickTest();

    expect(toasts.warning).toHaveBeenCalledWith(
      expect.stringContaining("was not checked"),
    );
    expect(toasts.success).not.toHaveBeenCalled();
  });

  it("keeps the plain failure message when the provider never answered", async () => {
    vi.spyOn(aiConnectionsApi, "test").mockRejectedValue(
      new Error("401 Unauthorized"),
    );

    await clickTest();

    expect(toasts.error).toHaveBeenCalledWith(
      expect.stringContaining("Check credentials"),
    );
  });

  it("shows the backend's refusal, not a generic sentence, on a 400", async () => {
    // A refusal for a private or unresolvable address is written for the
    // person filling the field in — a typo and a policy get different
    // sentences. A bare catch replaced all of it with "check the key and
    // URL", even when the key was fine.
    //
    // The mock sits at the network layer on purpose, and the request body
    // is examined: the test endpoint forbids extra fields, so a draft's
    // save-time baggage (name, tuning knobs) used to come back as a 422
    // about "name: Extra inputs are not permitted" — a pin at the api
    // boundary could not see that leak, because the shape it answered was
    // one the real screen never produced.
    // Earlier tests in this file spy on aiConnectionsApi.test; the spies
    // outlive their tests (clearAllMocks clears calls, not replacements),
    // and a stale one would answer before the real client ever built a
    // request. Restore the real client — this pin exercises it.
    vi.restoreAllMocks();
    let postedBody: Record<string, unknown> | null = null;
    server.use(
      http.post("*/api/v1/ai-connections/test", async ({ request }) => {
        postedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            detail: {
              code: "LLM_URL_UNRESOLVED",
              message:
                'AI connection base URL hostname "no-such-host.invalid" ' +
                "could not be resolved — check the spelling.",
            },
          },
          { status: 400 },
        );
      }),
    );

    await clickTest();
    await waitFor(() => expect(postedBody).not.toBeNull());

    expect(Object.keys(postedBody as unknown as object).sort()).toEqual([
      "api_base_url",
      "api_key",
      "capabilities",
      "model_name",
      "provider",
    ]);

    expect(toasts.error).toHaveBeenCalledWith(
      expect.stringContaining("could not be resolved — check the spelling"),
    );
    expect(toasts.error).not.toHaveBeenCalledWith(
      expect.stringContaining("Check the key"),
    );
    // The same sentence stands in the form, beside the button: the toast is
    // gone in seconds and the reader who pressed it is looking at the dialog.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not be resolved — check the spelling/,
    );
  });
});

/**
 * A refusal the reader cannot see is one they repeat — and the test is a
 * billed call, so repeating it spends the organization's budget again. The
 * toast is how this app reports a failed action, but it belongs to the whole
 * screen and it fades; the sentence has to stand where the button is.
 */
describe("AiConnectionFields — a failed test stands beside the button", () => {
  const draft = (over: Partial<AiConnectionDraft> = {}): AiConnectionDraft => ({
    ...empty,
    api_key: "sk-test",
    api_base_url: "https://openrouter.ai/api/v1",
    ...over,
  });

  const clickTest = async (value: AiConnectionDraft = draft()) => {
    const user = userEvent.setup();
    renderWithProviders(
      <AiConnectionFields value={value} onChange={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /Test connection/i }));
  };

  /**
   * Answer the test endpoint with `status`/`body` — the assertion is then
   * about what the reader sees, not about a mocked api client — and return a
   * probe for whether the endpoint was asked at all.
   */
  const answerWith = (status: number, body: JsonBodyType) => {
    let posted = false;
    server.use(
      http.post("*/api/v1/ai-connections/test", () => {
        posted = true;
        return HttpResponse.json(body, { status });
      }),
    );
    return () => posted;
  };

  beforeEach(() => {
    // The earlier pins spy on the api client, and a spy outlives its test.
    vi.restoreAllMocks();
  });

  it("puts a validation refusal (422) in the form, naming the field", async () => {
    // The screen in the report answered a 422 with nothing at all: the fields
    // were gone, the reply was gone, and pressing "Test connection" read as
    // having done nothing.
    answerWith(422, {
      detail: [
        {
          loc: ["body", "api_base_url"],
          msg: "Input should be a valid string",
          type: "string_type",
        },
      ],
    });

    await clickTest();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "api_base_url: Input should be a valid string",
    );
    // The click left the button where it started: not stuck mid-send.
    expect(
      screen.getByRole("button", { name: /Test connection/i }),
    ).toBeEnabled();
  });

  it("renders the limit refusal with the numbers the counter measured", async () => {
    // The gate refuses a test that would spend beyond the
    // organization's ceiling, and its 429 carries what was measured. It is a
    // refusal like any other here — the backend's sentence is the sentence on
    // screen, numbers and period included.
    answerWith(429, {
      detail: {
        code: "AI_USAGE_LIMIT_EXCEEDED",
        message:
          "The monthly AI limit is used up: 120 of 120 calls (1–30 September 2026).",
        limit_key: "ai_requests_monthly",
        used: 120,
        limit: 120,
        period_start: "2026-09-01",
        period_end: "2026-09-30",
      },
    });

    await clickTest();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /120 of 120 calls \(1–30 September 2026\)/,
    );
  });

  it("still says the test failed when a 5xx carries nothing readable", async () => {
    // A 5xx detail is written for whoever reads the logs; it is not handed to
    // the person at the screen. Silence is not the alternative — the failure
    // is still stated, in the one sentence this screen has for it.
    answerWith(503, { detail: "Traceback (most recent call last): KeyError" });

    await clickTest();

    const refusal = await screen.findByRole("alert");
    expect(refusal).toHaveTextContent(/Check credentials and base URL/);
    expect(refusal).not.toHaveTextContent(/Traceback/);
  });

  it("answers a draft with no key instead of hiding the button", async () => {
    const posted = answerWith(200, {});

    await clickTest(draft({ api_key: null }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Type the API key into the field above first/,
    );
    expect(posted()).toBe(false);
  });

  it("refuses a draft with no address to send it to", async () => {
    const posted = answerWith(200, {});

    await clickTest(draft({ provider: "custom", api_base_url: null }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Fill in the API base URL above first/,
    );
    expect(posted()).toBe(false);
  });
});
