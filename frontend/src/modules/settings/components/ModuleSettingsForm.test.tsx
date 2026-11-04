import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { QueryWrapper } from "@/test/queryWrapper";
import { signInWith, signOut } from "@/test/auth";
import { ModuleSettingsForm } from "./ModuleSettingsForm";
import { PageSaveProvider, usePageSave } from "@/module-sdk";
import type { ModuleSettingsSchema } from "@/lib/api/modules";

// Saving module settings is `admin:access` on the API — the form asks for it.
beforeEach(() => signInWith(["admin:access"]));
afterEach(signOut);

const updateSettings = vi.fn().mockResolvedValue({});

const renderForm = (ui: ReactElement) => render(ui, { wrapper: QueryWrapper });

// The real mutation hook runs: what the reader sees on a refusal is decided
// by how the form calls it, so the test must not replace it.
vi.mock("@/lib/api/modules", () => ({
  modulesApi: {
    updateSettings: (...args: unknown[]) => updateSettings(...args),
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// A nested schema, like the recipes module's — the shape the flat form state
// has to survive a round trip through.
const schema: ModuleSettingsSchema = {
  type: "object",
  properties: {
    jina: {
      type: "object",
      properties: {
        api_key: { type: "string", format: "secret", title: "Jina API key" },
      },
    },
    enable_cost_calculation: {
      type: "boolean",
      default: true,
      title: "Enable cost calculation",
    },
  },
};

describe("ModuleSettingsForm with a nested schema", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends the payload in the schema's shape, not with dotted keys", async () => {
    renderForm(
      <ModuleSettingsForm
        moduleName="recipes"
        schema={schema}
        initialValues={{}}
      />,
    );
    fireEvent.change(screen.getByTestId("field-jina.api_key"), {
      target: { value: "jina_abc" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    const payload = updateSettings.mock.calls[0][1];
    // `{"jina.api_key": …}` is rejected by the backend: the schema declares
    // `jina` as an object with `additionalProperties: false`.
    expect(Object.keys(payload)).not.toContain("jina.api_key");
    expect(payload).toEqual({
      jina: { api_key: "jina_abc" },
      enable_cost_calculation: true,
    });
  });

  it("shows a stored nested secret as already set", () => {
    renderForm(
      <ModuleSettingsForm
        moduleName="recipes"
        schema={schema}
        initialValues={{ jina: { api_key: "**********" } }}
      />,
    );
    // The masked marker has to reach the field, or the screen says no key is
    // stored and the user retypes one they already have. The value itself
    // cannot be shown — it never leaves the server unmasked — so the field
    // says a key exists instead.
    const input = screen.getByTestId("field-jina.api_key");
    expect(input).toHaveValue("");
    expect(input.getAttribute("placeholder")).toMatch(/stored/i);
  });

  it("leaves an untouched secret out of the payload instead of blanking it", async () => {
    renderForm(
      <ModuleSettingsForm
        moduleName="recipes"
        schema={schema}
        initialValues={{ jina: { api_key: "**********" } }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings.mock.calls[0][1]).toEqual({
      enable_cost_calculation: true,
    });
  });
});

describe("ModuleSettingsForm — a refused save", () => {
  it("shows the server's own sentence instead of failing silently", async () => {
    const sentence =
      "Ustawienie „warranty_warning_days” może wynosić najwyżej 365, podano 999";
    updateSettings.mockRejectedValueOnce(
      new AxiosError(
        "Request failed",
        "ERR_BAD_REQUEST",
        undefined,
        undefined,
        {
          status: 400,
          statusText: "Bad Request",
          headers: {},
          config: {} as never,
          data: { detail: sentence },
        },
      ),
    );
    renderForm(
      <ModuleSettingsForm
        moduleName="equipment"
        schema={schema}
        initialValues={{}}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(sentence));
  });
});

/**
 * At 390px this checkbox measured 13x20 on the three module-settings
 * routes that carry one: the bare square, squeezed by the flex row it sits in,
 * with no label around it to tap. jsdom has no layout, so these pin the
 * structure — the square keeps its size, the label around it
 * carries the target — and the live measurement is done in a browser.
 */
describe("ModuleSettingsForm — the boolean field is a 44px target", () => {
  it("wraps the checkbox in a label the thumb can land on", () => {
    renderForm(
      <ModuleSettingsForm
        moduleName="recipes"
        schema={schema}
        initialValues={{}}
      />,
    );

    const box = screen.getByRole("checkbox", {
      name: "Enable cost calculation",
    });
    expect(box.className).toContain("h-5");
    expect(box.className).toContain("w-5");

    const label = box.closest("label");
    expect(label).not.toBeNull();
    expect(label?.className).toContain("h-11");
    expect(label?.className).toContain("w-11");
    // Without this the row squeezes the box: `min-w-0` beside it, no shrink
    // guard of its own, and 20px of content in a 13px slot.
    expect(label?.className).toContain("shrink-0");
  });
});

describe("ModuleSettingsForm under a page with one Save", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function PageSave() {
    const { dirty, saveAll } = usePageSave();
    return (
      <button type="button" disabled={!dirty} onClick={() => void saveAll()}>
        page save
      </button>
    );
  }

  it("hands its edit to the page instead of showing a Save of its own", async () => {
    renderForm(
      <PageSaveProvider>
        <ModuleSettingsForm
          moduleName="recipes"
          schema={schema}
          initialValues={{}}
        />
        <PageSave />
      </PageSaveProvider>,
    );

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByRole("button", { name: "page save" })).toBeDisabled();

    fireEvent.click(screen.getByTestId("field-enable_cost_calculation"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "page save" })).toBeEnabled(),
    );
    expect(updateSettings).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "page save" }));

    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings.mock.calls[0][1]).toMatchObject({
      enable_cost_calculation: false,
    });
    // The page says "saved" once for everything it wrote.
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("ModuleSettingsForm — a number outside its bounds", () => {
  const windowSchema: ModuleSettingsSchema = {
    type: "object",
    properties: {
      warning_window_days: {
        type: "integer",
        minimum: 1,
        maximum: 365,
        default: 30,
        title: "Warning window",
      },
    },
  };

  it("answers in the app's own words and does not save, instead of the browser's bubble", async () => {
    vi.clearAllMocks();
    const { container } = renderForm(
      <ModuleSettingsForm
        moduleName="equipment"
        schema={windowSchema}
        initialValues={{}}
      />,
    );
    fireEvent.change(screen.getByTestId("field-warning_window_days"), {
      target: { value: "-3" },
    });

    // The message is the app's, in the app's language, and rides on the field.
    expect(
      screen.getByText("Enter a number from 1 to 365."),
    ).toBeInTheDocument();
    // The browser's own validation is off, so its bubble cannot answer first.
    expect(container.querySelector("form")).toHaveAttribute("novalidate");

    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(updateSettings).not.toHaveBeenCalled());
  });

  it("refuses a fraction on a whole-number setting in the app's own words", async () => {
    vi.clearAllMocks();
    renderForm(
      <ModuleSettingsForm
        moduleName="equipment"
        schema={windowSchema}
        initialValues={{}}
      />,
    );
    fireEvent.change(screen.getByTestId("field-warning_window_days"), {
      target: { value: "1.5" },
    });

    expect(screen.getByText("Enter a whole number.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(updateSettings).not.toHaveBeenCalled());
  });

  it("saves once the number is back in range", async () => {
    vi.clearAllMocks();
    renderForm(
      <ModuleSettingsForm
        moduleName="equipment"
        schema={windowSchema}
        initialValues={{}}
      />,
    );
    fireEvent.change(screen.getByTestId("field-warning_window_days"), {
      target: { value: "14" },
    });
    expect(screen.queryByText(/Enter a number/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(updateSettings).toHaveBeenCalledWith("equipment", {
        warning_window_days: 14,
      }),
    );
  });
});
