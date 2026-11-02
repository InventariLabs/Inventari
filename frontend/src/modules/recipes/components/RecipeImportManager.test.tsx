import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import axios from "axios";
import type { TFunction } from "i18next";

import { RecipeImportManager } from "./RecipeImportManager";
import type { AiPurpose } from "@/types/ai";

const previewMock = vi.fn();

vi.mock("@/modules/recipes/hooks/useRecipes", () => ({
  usePreviewImport: () => ({ mutateAsync: previewMock, isPending: false }),
  useCreateRecipe: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

const purposes: AiPurpose[] = [];
let purposesFailed = false;

vi.mock("@/modules/settings/hooks/useAiConnections", () => ({
  useAiPurposes: () => ({
    data: purposesFailed ? undefined : purposes,
    isError: purposesFailed,
  }),
}));

/**
 * The manager takes its translator as a prop; the stub resolves the handful
 * of sentences under test and interpolates like i18next would, so an
 * assertion can demand the registry's label and never the raw key.
 */
const t = ((key: string, opts?: Record<string, unknown>) => {
  const strings: Record<string, string> = {
    "recipes:import_export.import_title": "Import recipe",
    "recipes:import_export.import_from_url": "Import from URL",
    "recipes:import_export.import_from_json": "Import from JSON",
    "recipes:import_export.import_url_placeholder": "url",
    "recipes:import_export.import_json_placeholder": "paste",
    "recipes:import_export.show_example": "Insert example format",
    "recipes:import_export.example_replace_title": "Replace your text?",
    "recipes:import_export.example_replace_message":
      "The example would replace the JSON in the field.",
    "recipes:import_export.example_replace_confirm": "Replace",
    "recipes:import_export.import_submit": "Import",
    "recipes:import_export.review_parsing": "Parsing…",
    "recipes:import_export.invalid_url": "Invalid URL",
    "recipes:import_export.invalid_json": "Not valid JSON",
    "recipes:import_export.import_error": "Import failed: {{error}}",
    "recipes:import_export.import_error_unknown": "the server gave no reason",
    "recipes:import_export.ai_connection_required":
      "Reading a page needs an AI connection — “{{purpose}}” is not configured yet.",
    "recipes:import_export.set_up_ai_connection":
      "Set one up in Settings → AI Connections",
    "recipes:import_export.import_error_ai_not_configured":
      "Import failed: “{{purpose}}” needs an AI connection.",
    "recipes:ai.purposeLabel": "Read a recipe from text",
    "common:form.cancel": "Cancel",
  };
  let out = strings[key] ?? key;
  if (opts) {
    for (const [name, value] of Object.entries(opts)) {
      out = out.split(`{{${name}}}`).join(String(value));
    }
  }
  return out;
}) as unknown as TFunction;

function purposeBound(
  bound_connection_id: string | null,
  usable: boolean,
): AiPurpose {
  return {
    key: "recipes.text_parse",
    label_key: "recipes:ai.purposeLabel",
    description_key: "recipes:ai.purposeDesc",
    owner_module: "recipes",
    capability: "text",
    bound_connection_id,
    usable,
  };
}

function renderManager() {
  return render(
    <MemoryRouter>
      <RecipeImportManager t={t} onClose={vi.fn()} onImported={vi.fn()} />
    </MemoryRouter>,
  );
}

describe("RecipeImportManager — the import modal knows what the AI registry knows", () => {
  beforeEach(() => {
    previewMock.mockReset();
    purposes.length = 0;
    purposesFailed = false;
  });

  it("keeps the URL tab open and the server refusal readable when the registry could not be read", async () => {
    // Deliberate degradation: the registry only pre-empts the refusal, so a
    // failed read falls back to the generic label instead of blocking the tab.
    purposesFailed = true;
    previewMock.mockRejectedValue(
      new axios.AxiosError(
        "service unavailable",
        undefined,
        undefined,
        undefined,
        {
          status: 503,
          statusText: "Service Unavailable",
          headers: {},
          config: undefined,
          data: { detail: { code: "LLM_PURPOSE_UNBOUND", message: "unbound" } },
        } as never,
      ),
    );
    renderManager();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("url"), {
      target: { value: "https://example.com/recipe" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Import failed: “Read a recipe from text”",
    );
  });

  it("offers the URL tab while a connection is bound", () => {
    purposes.push(purposeBound("conn-1", true));
    renderManager();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled(); // no URL yet
  });

  it("blocks URL import with the registry label when nothing is bound", () => {
    purposes.push(purposeBound(null, false));
    renderManager();
    expect(
      screen.getByText(/“Read a recipe from text” is not configured yet/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("blocks URL import when the chosen connection cannot serve the purpose", () => {
    // The org's choice stays readable — bound_connection_id still names it
    // — while the verdict refuses it: the same 503 state the text-only
    // binding produced for the vision screens.
    purposes.push(purposeBound("conn-1", false));
    renderManager();
    expect(
      screen.getByText(/“Read a recipe from text” is not configured yet/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("answers an LLM_PURPOSE_UNBOUND refusal with the label, not the key", async () => {
    // The race: the registry still shows a binding, so the tab is offered —
    // but the binding vanished server-side before the click landed.
    purposes.push(purposeBound("conn-1", true));
    previewMock.mockRejectedValue(
      new axios.AxiosError(
        "service unavailable",
        undefined,
        undefined,
        undefined,
        {
          status: 503,
          statusText: "Service Unavailable",
          headers: {},
          config: undefined,
          data: {
            detail: {
              code: "LLM_PURPOSE_UNBOUND",
              message: "No AI connection has been chosen for this feature yet.",
            },
          },
        } as never,
      ),
    );
    renderManager();
    fireEvent.change(screen.getByPlaceholderText("url"), {
      target: { value: "https://example.com/recipe" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Import failed: “Read a recipe from text”");
    expect(alert).not.toHaveTextContent("recipes.text_parse");
  });

  it("keeps the pasted-JSON path outside the AI gate", async () => {
    const user = userEvent.setup();
    purposes.push(purposeBound(null, false));
    renderManager();
    await user.click(screen.getByRole("tab", { name: "Import from JSON" }));
    fireEvent.change(screen.getByPlaceholderText("paste"), {
      target: { value: '{"name": "Soup"}' },
    });
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
  });
});

describe("RecipeImportManager — the example does not eat what was pasted", () => {
  beforeEach(() => {
    previewMock.mockReset();
    purposes.length = 0;
  });

  async function openJsonTabWith(text: string) {
    const user = userEvent.setup();
    renderManager();
    await user.click(screen.getByRole("tab", { name: "Import from JSON" }));
    if (text) {
      fireEvent.change(screen.getByPlaceholderText("paste"), {
        target: { value: text },
      });
    }
    return user;
  }

  it("fills an empty field at once", async () => {
    const user = await openJsonTabWith("");
    await user.click(
      screen.getByRole("button", { name: "Insert example format" }),
    );
    expect(
      (screen.getByPlaceholderText("paste") as HTMLTextAreaElement).value,
    ).toContain('"name": "Example Recipe"');
    expect(screen.queryByText("Replace your text?")).not.toBeInTheDocument();
  });

  it("asks before it replaces text that was pasted, and keeps it on cancel", async () => {
    // A long recipe pasted, one field corrected, one curious click on the
    // example link, and the only copy of the work was gone with no way back.
    const user = await openJsonTabWith("abc");
    await user.click(
      screen.getByRole("button", { name: "Insert example format" }),
    );
    expect(await screen.findByText("Replace your text?")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("paste")).toHaveValue("abc");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByPlaceholderText("paste")).toHaveValue("abc");
  });

  it("replaces the text once the reader agrees", async () => {
    const user = await openJsonTabWith("abc");
    await user.click(
      screen.getByRole("button", { name: "Insert example format" }),
    );
    await user.click(await screen.findByRole("button", { name: "Replace" }));
    expect(
      (screen.getByPlaceholderText("paste") as HTMLTextAreaElement).value,
    ).toContain('"name": "Example Recipe"');
  });
});
