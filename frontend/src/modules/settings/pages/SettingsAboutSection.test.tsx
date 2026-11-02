import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { USER_GUIDE_URL } from "@/lib/userGuide";
import SettingsAboutSection from "./SettingsAboutSection";

const ABOUT = {
  name: "Inventari",
  version: "0.9.0",
  license: "AGPL-3.0-only",
  license_url: "https://www.gnu.org/licenses/agpl-3.0.html",
  source_code_url: "https://git.example.org/acme/inventari",
};

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <SettingsAboutSection />
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

function serve(body: object) {
  server.use(http.get("*/about", () => HttpResponse.json(body)));
}

describe("SettingsAboutSection", () => {
  it("names the version the server runs and says there is no warranty", async () => {
    serve(ABOUT);
    renderSection();

    expect(
      await screen.findByRole("heading", { name: "Inventari 0.9.0" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/without any warranty/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Read the licence/ }),
    ).toHaveAttribute("href", ABOUT.license_url);
  });

  it("links the user guide next to the licence and the source", async () => {
    serve(ABOUT);
    renderSection();

    expect(
      await screen.findByRole("link", { name: /Open the user guide/ }),
    ).toHaveAttribute("href", USER_GUIDE_URL);
  });

  it("links the source the installation is configured with, so a fork offers its own", async () => {
    serve(ABOUT);
    renderSection();

    expect(
      await screen.findByRole("link", { name: /Get the source code/ }),
    ).toHaveAttribute("href", "https://git.example.org/acme/inventari");
  });

  it("shows a configured value that is not a web address as text, never as a link", async () => {
    serve({ ...ABOUT, source_code_url: "javascript:alert(1)" });
    renderSection();

    expect(await screen.findByText("javascript:alert(1)")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Get the source code/ }),
    ).not.toBeInTheDocument();
  });

  it("offers a retry when the server does not answer, instead of a missing link", async () => {
    server.use(
      http.get("*/about", () => HttpResponse.json({}, { status: 500 })),
    );
    renderSection();

    expect(
      await screen.findByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Get the source code/ }),
    ).not.toBeInTheDocument();
  });
});
