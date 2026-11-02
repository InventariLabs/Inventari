import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TemplatePreviewFrame } from "./TemplatePreviewFrame";
import { templatesApi } from "@/modules/shared/lib/templates";
import { withLanguage } from "@/test/mocks/i18n";

vi.mock("@/modules/shared/lib/templates", () => ({
  templatesApi: { preview: vi.fn() },
}));

const renderFrame = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TemplatePreviewFrame module="warehouse" bodyHtml="<h1>x</h1>" />
    </QueryClientProvider>,
  );

const axiosError = (detail: unknown, status = 422) =>
  Object.assign(new Error("Request failed with status code " + status), {
    isAxiosError: true,
    response: { status, data: { detail } },
  });

describe("TemplatePreviewFrame — a failed render says why", () => {
  beforeEach(() => {
    vi.mocked(templatesApi.preview).mockReset();
  });

  it("shows the backend's reason, which names the Jinja problem", async () => {
    vi.mocked(templatesApi.preview).mockRejectedValue(
      axiosError(
        "Template could not be rendered: unexpected 'end of template', expected 'endfor'",
      ),
    );
    renderFrame();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("unexpected 'end of template'");
  });

  it("keeps the neutral sentence when the error carries nothing", async () => {
    vi.mocked(templatesApi.preview).mockRejectedValue(
      axiosError({ detail: ["not", "a", "message"] }),
    );
    renderFrame();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This layout does not render.",
    );
  });

  it("does not call the layout broken when the server failed", async () => {
    vi.mocked(templatesApi.preview).mockRejectedValue(axiosError(null, 500));
    renderFrame();

    const alert = await screen.findByRole("alert");
    expect(alert).not.toHaveTextContent("This layout does not render.");
    expect(alert).toHaveTextContent(/server problem/);
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("renders the preview html through the frame", async () => {
    vi.mocked(templatesApi.preview).mockResolvedValue("<html>ok</html>");
    renderFrame();

    await screen.findByTitle(/template/i);
    await vi.waitFor(() => {
      const frame = screen.getByTitle(/template/i) as HTMLIFrameElement;
      expect(frame.getAttribute("srcdoc")).toContain("<html>ok</html>");
    });
  });
});

describe("TemplatePreviewFrame — the UI language is part of the answer", () => {
  beforeEach(() => {
    vi.mocked(templatesApi.preview).mockReset();
  });

  it("asks again when the same layout is reopened in another language", async () => {
    vi.mocked(templatesApi.preview).mockResolvedValue("<html>ok</html>");
    // The app keeps an answer fresh for minutes and a closed dialog's answer
    // in the cache; the suite's client forbids both, which would hide a
    // stale-language preview surviving a reopen.
    const client = new QueryClient();
    client.setDefaultOptions({
      queries: { staleTime: 5 * 60 * 1000, gcTime: 5 * 60 * 1000 },
    });
    const open = () =>
      render(
        <QueryClientProvider client={client}>
          <TemplatePreviewFrame module="warehouse" bodyHtml="<h1>x</h1>" />
        </QueryClientProvider>,
      );

    const first = open();
    await vi.waitFor(() =>
      expect(templatesApi.preview).toHaveBeenCalledTimes(1),
    );
    first.unmount();

    await withLanguage("de", async () => {
      open();
      await vi.waitFor(() =>
        expect(templatesApi.preview).toHaveBeenCalledTimes(2),
      );
    });
  });
});
