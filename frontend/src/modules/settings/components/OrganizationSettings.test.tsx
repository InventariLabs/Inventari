import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { CURRENCY_CODES } from "@/lib/currencies";
import { TIMEZONE_CODES } from "@/lib/timezones";
import { organizationsApi } from "@/lib/api/organizations";
import { useFormGuardStore } from "@/store/formGuardStore";
import OrganizationSettings from "./OrganizationSettings";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

// Only the upload is replaced: every other request on this screen is JSON and
// goes through the mock server like the rest of the suite. See `refuseUpload`
// for why this one cannot.
vi.mock("@/lib/api/organizations", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/organizations")>();
  return {
    ...actual,
    organizationsApi: {
      ...actual.organizationsApi,
      uploadLogo: vi.fn(),
    },
  };
});

const authState = {
  user: { role: "admin", is_superuser: false, permissions: [] as string[] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

const org = {
  id: "org-1",
  name: "Test Org",
  currency: "PLN",
  created_at: "2026-01-01T00:00:00Z",
  created_by: null,
  enabled_modules: ["core", "items"],
  settings: {},
};

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OrganizationSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  server.use(
    http.get("*/organizations/my", () => HttpResponse.json(org)),
    http.get("*/organizations/my/invitations", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("*/organizations/my/members", () => HttpResponse.json([])),
    http.get("*/organizations/my/registration-requests", () =>
      HttpResponse.json([]),
    ),
    http.get("*/auth/registration-requests", () =>
      HttpResponse.json(onePage([])),
    ),
  );
});

describe("OrganizationSettings — currency", () => {
  it("offers the one currency list the rest of the application offers", async () => {
    renderSettings();

    const select = (await screen.findByDisplayValue(
      /^PLN/,
    )) as HTMLSelectElement;
    const offered = Array.from(select.querySelectorAll("option")).map(
      (option) => option.value,
    );
    expect(offered).toEqual([...CURRENCY_CODES]);
  });

  it("says that a changed currency does not convert what is already recorded", async () => {
    renderSettings();

    const select = await screen.findByDisplayValue(/^PLN/);
    expect(screen.queryByText(/nothing is converted/i)).not.toBeInTheDocument();

    await userEvent.selectOptions(select, "CHF");

    await waitFor(() => {
      expect(screen.getByText(/nothing is converted/i)).toBeInTheDocument();
    });
  });
});

describe("OrganizationSettings — timezone", () => {
  it("preselects the organization's zone and keeps it selectable when off the curated list", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, timezone: "Pacific/Chatham" }),
      ),
    );
    renderSettings();

    const select = (await screen.findByDisplayValue(
      /^Pacific\/Chatham/,
    )) as HTMLSelectElement;
    const offered = Array.from(select.querySelectorAll("option")).map(
      (option) => option.value,
    );
    expect(offered).toContain("Pacific/Chatham");
    expect(offered).toContain("UTC");
    expect(offered.length).toBeGreaterThanOrEqual(TIMEZONE_CODES.length);
  });

  it("saves the timezone the administrator picked", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, timezone: "UTC" }),
      ),
    );
    let savedPayload: Record<string, unknown> = {};
    server.use(
      http.put("*/organizations", async ({ request }) => {
        savedPayload = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...org });
      }),
    );
    renderSettings();

    const select = await screen.findByDisplayValue(/^UTC/);
    await userEvent.selectOptions(select, "Europe/Warsaw");

    // The organization card renders before the issuer card, so its save
    // button is the first one on the screen.
    await userEvent.click(screen.getAllByRole("button", { name: /save/i })[0]);

    await waitFor(() => {
      expect(savedPayload.timezone).toBe("Europe/Warsaw");
    });
  });
});

/**
 * What the reader gets when the server says no. The backend writes these
 * refusals in the language the request asked for and they name the rule that
 * was broken — "only image files", "the image is too large (max 5 MB)" — so a
 * toast that prints a sentence of its own throws away the only part of the
 * answer that can be acted on. The fallback stays for a server that says
 * nothing; it is not the message for a server that spoke.
 */
describe("OrganizationSettings — refusals arrive in the server's words", () => {
  /**
   * The logo upload is the one request here that cannot be answered by the
   * mock server: it travels as multipart, and a multipart XHR never settles in
   * jsdom — MSW answers it, the browser object drops the response, and the
   * mutation stays pending forever. `applyRequestHeaders` documents the same
   * blind spot from the other side. So the refusal is delivered at the API
   * boundary, shaped exactly as axios rejects it.
   */
  function refuseUpload(status: number, detail: Record<string, string>) {
    vi.mocked(organizationsApi.uploadLogo).mockRejectedValue(
      Object.assign(new Error(`Request failed with status code ${status}`), {
        isAxiosError: true,
        response: { status, data: { detail } },
      }),
    );
  }

  async function pickLogo(file: File) {
    const { container } = renderSettings();
    await screen.findByRole("button", { name: /upload logo/i });
    // The picker is hidden and opened by that button, so `userEvent.upload`
    // — which drives a pointer click and would land on whatever is painted —
    // cannot reach it. The change is dispatched the way the browser's own file
    // chooser would, with the file already in `input.files`.
    fireEvent.change(
      container.querySelector("input[type=file]") as HTMLInputElement,
      { target: { files: [file] } },
    );
  }

  it("says which files the logo may be, not that something went wrong", async () => {
    // The `accept` attribute is advice, not a gate: the picker hides a .txt but
    // a drag or an "all files" choice delivers one, which is why the server
    // refuses it at all — and why its refusal is the sentence worth showing.
    refuseUpload(400, {
      code: "only_image_files_allowed",
      message: "Dozwolone są tylko pliki graficzne (jpg, png, gif, webp)",
    });

    await pickLogo(
      new File(["not an image"], "bad.txt", { type: "text/plain" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Dozwolone są tylko pliki graficzne (jpg, png, gif, webp)",
      ),
    );
  });

  it("names the ceiling when the logo is too large", async () => {
    refuseUpload(413, {
      code: "FILE_TOO_LARGE",
      message: "Obraz jest zbyt duży (maks. 5 MB)",
    });

    await pickLogo(
      new File([new Uint8Array(6 * 1024 * 1024)], "big.png", {
        type: "image/png",
      }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Obraz jest zbyt duży (maks. 5 MB)",
      ),
    );
  });

  it("shows what the server objected to when saving the issuer block", async () => {
    server.use(
      http.put("*/organizations", () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message: "Numer NIP nie pasuje do wybranego kraju.",
            },
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSettings();

    await user.type(await screen.findByLabelText(/tax id/i), "1234567890");
    // The organization card renders above the issuer card, so the issuer's
    // save button is the second one.
    await user.click(screen.getAllByRole("button", { name: /^save$/i })[1]);

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Numer NIP nie pasuje do wybranego kraju.",
      ),
    );
  });

  it("shows the server's reason when the logo cannot be removed", async () => {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...org, logo_url: "organizations/logo.png" }),
      ),
      http.delete("*/organizations/logo", () =>
        HttpResponse.json(
          {
            detail: {
              code: "FORBIDDEN",
              message: "Brak uprawnień administratora organizacji.",
            },
          },
          { status: 403 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSettings();

    await user.click(
      await screen.findByRole("button", { name: /remove logo/i }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Brak uprawnień administratora organizacji.",
      ),
    );
  });
});

describe("OrganizationSettings — a save says what was saved", () => {
  it("names the issuer block, not a bare success, when it is saved", async () => {
    server.use(
      http.put("*/organizations", () => HttpResponse.json({ ...org })),
    );
    const user = userEvent.setup();
    renderSettings();

    await user.type(await screen.findByLabelText(/tax id/i), "1234567890");
    await user.click(screen.getAllByRole("button", { name: /^save$/i })[1]);

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Document issuer saved"),
    );
  });

  it("names the organization settings when the first card is saved", async () => {
    server.use(
      http.put("*/organizations", () => HttpResponse.json({ ...org })),
    );
    const user = userEvent.setup();
    renderSettings();

    const select = await screen.findByDisplayValue(/^UTC/);
    await user.selectOptions(select, "Europe/Warsaw");
    await user.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Organization settings saved"),
    );
  });
});

describe("OrganizationSettings — the navigation gate knows about unsaved work", () => {
  it("reports the organization card's unsaved work to the gate", async () => {
    renderSettings();

    const name = await screen.findByLabelText(/organization name/i);
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    await userEvent.type(name, "X");

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });
  });

  it("reports the issuer card's unsaved work to the gate too", async () => {
    renderSettings();

    const taxId = await screen.findByLabelText(/tax id/i);
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    await userEvent.type(taxId, "1");

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });
  });

  it("disarms the gate when the typed value goes back to the saved one", async () => {
    renderSettings();

    const name = await screen.findByLabelText(/organization name/i);
    await userEvent.type(name, "X");
    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });

    fireEvent.change(name, { target: { value: "Test Org" } });

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();
    });
  });

  it("clears the gate when the screen unmounts", async () => {
    const view = renderSettings();

    const name = await screen.findByLabelText(/organization name/i);
    await userEvent.type(name, "X");
    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });

    view.unmount();

    expect(useFormGuardStore.getState().dirtyForm).toBeNull();
  });
});

describe("OrganizationSettings — requests for access", () => {
  const pending = {
    id: "r1",
    email: "asks@example.com",
    full_name: "Asking Person",
    preferred_language: "en",
    created_at: "2026-09-20T10:00:00Z",
    accepted_at: null,
    rejected_at: null,
    is_rejected: false,
  };

  afterEach(() => {
    authState.user.is_superuser = false;
  });

  it("does not ask an administrator for requests only the superuser can decide", async () => {
    let asked = 0;
    server.use(
      http.get("*/auth/registration-requests", () => {
        asked += 1;
        return HttpResponse.json(onePage([pending]));
      }),
    );
    renderSettings();

    await screen.findByDisplayValue(/^PLN/);
    expect(asked).toBe(0);
    expect(screen.queryByText("Asking Person")).not.toBeInTheDocument();
  });

  it("shows a pending request to the superuser, who can decide it", async () => {
    authState.user.is_superuser = true;
    server.use(
      http.get("*/auth/registration-requests", () =>
        HttpResponse.json(onePage([pending])),
      ),
    );
    renderSettings();

    expect(await screen.findByText("Asking Person")).toBeInTheDocument();
  });
});

describe("OrganizationSettings — organization read fails", () => {
  it("states the failure and offers no Save that could write defaults over the stored values", async () => {
    let writes = 0;
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
      http.put("*/organizations", () => {
        writes += 1;
        return HttpResponse.json(org);
      }),
    );
    renderSettings();

    expect(
      await screen.findByText("Could not load the organization"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByLabelText(/Currency/)).toBeNull();
    expect(screen.queryByLabelText(/Timezone/)).toBeNull();
    expect(writes).toBe(0);
  });

  it("keeps the cards away while Try again is still waiting for the organization", async () => {
    let calls = 0;
    let writes = 0;
    server.use(
      http.get("*/organizations/my", async () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json({ detail: "boom" }, { status: 500 });
        }
        await new Promise(() => {});
      }),
      http.put("*/organizations", () => {
        writes += 1;
        return HttpResponse.json(org);
      }),
    );
    renderSettings();

    await userEvent.click(
      await screen.findByRole("button", { name: /try again|retry/i }),
    );
    await waitFor(() => expect(calls).toBe(2));

    expect(screen.queryByLabelText(/organization name/i)).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(writes).toBe(0);
  });
});
