import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  TemplateEditorModal,
  hasBalancedHtml,
} from "@/modules/shared/components/TemplateEditorModal";
import { server } from "@/test/mocks/server";
import { errorAlways } from "@/test/mocks/errors";
import { withLanguage } from "@/test/mocks/i18n";
import { http, HttpResponse } from "msw";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const mockPlaceholders = [
  { key: "{{document_number}}", description: "Document number" },
  { key: "{{partner_name}}", description: "Partner name" },
];

const documentTypes = [
  { value: "STANDARD", label: "Standard" },
  { value: "PL_PZ", label: "PL PZ" },
];

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe("hasBalancedHtml", () => {
  it("accepts balanced markup", () => {
    expect(hasBalancedHtml("<p>Hello</p>")).toBe(true);
    expect(hasBalancedHtml("<div><span>x</span></div>")).toBe(true);
    expect(hasBalancedHtml("<table><tr><td>1</td></tr></table>")).toBe(true);
    expect(hasBalancedHtml("<img src='x' /><br>")).toBe(true);
  });

  it("rejects unbalanced or unclosed markup", () => {
    expect(hasBalancedHtml("<div><span>x</div>")).toBe(false);
    expect(hasBalancedHtml("<p>Hello")).toBe(false);
    expect(hasBalancedHtml("</p>")).toBe(false);
  });
});

describe("TemplateEditorModal", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/warehouse/templates/placeholders", () =>
        HttpResponse.json(mockPlaceholders),
      ),
    );
  });

  it("renders create mode", async () => {
    render(
      <TemplateEditorModal
        module="warehouse"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(
        screen.getAllByText("Create Template").length,
      ).toBeGreaterThanOrEqual(1);
    });
  });

  it("renders edit mode when template provided", async () => {
    const template = {
      id: "tpl-1",
      module: "warehouse",
      name: "My Template",
      document_type: "STANDARD",
      body_html: "<p>Hello</p>",
      version: 1,
      is_default: false,
      created_by: null,
      created_at: "2024-01-01T00:00:00Z",
      updated_at: "2024-01-01T00:00:00Z",
      source_outdated: false,
    };

    render(
      <TemplateEditorModal
        module="warehouse"
        template={template}
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Edit Template")).toBeInTheDocument();
    });
  });

  it("says the placeholders did not load, with a retry, instead of an empty panel", async () => {
    errorAlways("/api/v1/warehouse/templates/placeholders", 500);
    render(
      <TemplateEditorModal
        module="warehouse"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/error/i);
    expect(
      within(alert).getByRole("button", { name: /try again/i }),
    ).toBeVisible();
    expect(screen.queryByText("Document number")).not.toBeInTheDocument();
  });

  it("shows placeholders list", async () => {
    render(
      <TemplateEditorModal
        module="warehouse"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Document number")).toBeInTheDocument();
      expect(screen.getByText("Partner name")).toBeInTheDocument();
    });
  });

  it("sets the key, the description and the example in tokens that read on the raised surface", async () => {
    // The list sits on the raised surface. The muted token measured 4.07:1
    // there in dark and the example's /70 opacity 2.8:1; the brand-text token
    // carries the key and the secondary one the lines under it.
    server.use(
      http.get("*/api/v1/purchase-orders/templates/placeholders", () =>
        HttpResponse.json([
          {
            key: "{{document_number}}",
            description: "Document number",
            example: "PO/2026/001",
          },
        ]),
      ),
    );
    render(
      <TemplateEditorModal
        module="purchase-orders"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    const key = await screen.findByText("{{document_number}}");
    expect(key).toHaveClass("text-on-primary");
    expect(key.className).not.toContain("/70");
    expect(screen.getByText("Document number")).toHaveClass(
      "text-on-secondary",
    );
    const example = screen.getByText(/PO\/2026\/001/);
    expect(example).toHaveClass("text-on-secondary");
    expect(example).not.toHaveClass("text-on-muted");
  });

  it("calls onClose when close button clicked", async () => {
    const user = userEvent.setup();
    render(
      <TemplateEditorModal
        module="warehouse"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(
        screen.getAllByText("Create Template").length,
      ).toBeGreaterThanOrEqual(1);
    });

    const closeBtn = screen.getByText("×");
    await user.click(closeBtn);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the typed template when the save is rejected with 409", async () => {
    const user = userEvent.setup();
    errorAlways("/api/v1/warehouse/templates", 409, {
      method: "post",
      code: "TEMPLATE_NAME_TAKEN",
      message: "A template with this name already exists",
    });

    render(
      <TemplateEditorModal
        module="warehouse"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(
        screen.getAllByText("Create Template").length,
      ).toBeGreaterThanOrEqual(1);
    });

    const nameField = screen.getByPlaceholderText(
      "e.g. Company Handover Protocol",
    );
    await user.type(nameField, "Handover");
    await user.type(screen.getByPlaceholderText("<html>..."), "<p>Hi</p>");

    await user.click(screen.getByRole("button", { name: "Create Template" }));

    // The work survives the rejection and the modal stays open. No message is
    // shown — useCreateTemplate passes no errorFallback to useAppMutation, so
    // a rejected save is silent. Asserting the silence would bless it; this
    // asserts only what is true and correct today.
    await waitFor(() => {
      expect(nameField).toHaveValue("Handover");
    });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("offers the preview toggle only where the module can serve it", async () => {
    // Equipment has no preview endpoint: the toggle used to render there and
    // the frame asked an address the backend does not expose, so the panel
    // answered with the render-failure sentence for a completely different
    // reason. Without support the editor offers no control at all.
    server.use(
      http.get("/api/v1/equipment/templates/placeholders", () =>
        HttpResponse.json(mockPlaceholders),
      ),
    );

    render(
      <TemplateEditorModal
        module="equipment"
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Document number")).toBeInTheDocument();
    });
    expect(screen.queryByText("Show preview")).not.toBeInTheDocument();
  });

  it("sets the preview toggle in the brand text token, not the raw ramp", async () => {
    // text-primary-500 measured 3.68:1 on white and 4.05:1 on the dark card.
    render(
      <TemplateEditorModal
        module="warehouse"
        previewSupported
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );
    const toggle = await screen.findByRole("button", { name: /show preview/i });
    expect(toggle).toHaveClass("text-on-primary");
    expect(toggle.className).not.toMatch(/text-primary-\d/);
  });

  it("resolves the tooltip through the same catalogue as the line under it", async () => {
    // Two readings of one placeholder were resolved separately, so the
    // catalogue reached only the second: hovering a symbol answered in the
    // API's English while the text under it spoke the reader's language.
    server.use(
      http.get("*/api/v1/purchase-orders/templates/placeholders", () =>
        HttpResponse.json(mockPlaceholders),
      ),
    );

    await withLanguage("pl", async () => {
      render(
        <TemplateEditorModal
          module="purchase-orders"
          documentTypes={documentTypes}
          i18nNamespace="purchase_orders"
          placeholderDescriptions={[
            {
              key: "{{document_number}}",
              descriptionKey: "templates.placeholders.po_number",
            },
          ]}
          onClose={onClose}
        />,
        { wrapper: createWrapper() },
      );

      const button = (await screen.findByText("{{document_number}}")).closest(
        "button",
      );

      expect(button).toHaveAttribute(
        "title",
        "Numer ZP (generowany automatycznie)",
      );
      expect(button).toHaveTextContent("Numer ZP (generowany automatycznie)");
    });
  });

  it("documents can preview its draft render", async () => {
    render(
      <TemplateEditorModal
        module="warehouse"
        previewSupported
        documentTypes={documentTypes}
        placeholderDescriptions={[]}
        onClose={onClose}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("Show preview")).toBeInTheDocument();
    });
  });
});
