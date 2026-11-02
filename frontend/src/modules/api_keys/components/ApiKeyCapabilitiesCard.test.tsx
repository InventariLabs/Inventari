import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import ApiKeyCapabilitiesCard from "./ApiKeyCapabilitiesCard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const capabilities = {
  catalog: [
    {
      key: "org:members:write",
      label_key: "permissions:system.org_members_write",
      description_key: null,
    },
  ],
  grantable: [],
  default_permissions: [],
  withheld_permissions: ["org:members:write"],
  admin_areas_blocked: true,
  header: "X-API-Key",
  scopes: [],
};

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeyCapabilitiesCard />
    </QueryClientProvider>,
  );
}

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
}

describe("ApiKeyCapabilitiesCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("reads the capabilities again when the reader retries a failed load", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/api-keys/capabilities", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(capabilities);
      }),
    );
    renderCard();

    await userEvent.click(
      await screen.findByRole("button", { name: /try again/i }),
    );

    expect(await screen.findByText("Manage members")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("copies the example request with the server's header name and confirms it", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json({ ...capabilities, header: "X-Custom-Key" }),
      ),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    renderCard();

    await userEvent.click(await screen.findByRole("button", { name: /copy/i }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain(
      "curl -H 'X-Custom-Key: inv_live_…'",
    );
    expect(writeText.mock.calls[0][0]).toContain("/api/v1/items");
  });

  it("explains instead of confirming when the clipboard refuses the text", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities),
      ),
    );
    stubClipboard(() => Promise.reject(new Error("denied")));
    renderCard();

    await userEvent.click(await screen.findByRole("button", { name: /copy/i }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
