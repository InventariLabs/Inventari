import { describe, it, expect, beforeEach, vi } from "vitest";
import { useAuthStore } from "./authStore";
import { useScanStore } from "./scanStore";
import { useFormMemoryStore } from "./formMemoryStore";
import { addRecentItem, getRecentItems } from "@/lib/recentItems";
import { tokenStore } from "../lib/api/client";
import { rememberLanguageChoice } from "../i18n/languageChoice";
import i18n from "../i18n/config";
import { act } from "react";

describe("authStore", () => {
  beforeEach(() => {
    // Reset store state before each test
    act(() => {
      useAuthStore.setState({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        authUnavailable: false,
      });
    });
    localStorage.clear();
    tokenStore.clear();
  });

  it("should login successfully", async () => {
    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.user).not.toBeNull();
    expect(state.user?.email).toBe("test@example.com");
    expect(tokenStore.get()).toBe("mocked_access_token");
  });

  it("adopts a language picked before signing in", async () => {
    // The sign-in screen has a language selector but no session to save to.
    rememberLanguageChoice("pl");

    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    expect(i18n.language).toBe("pl");
    // Consumed, so the next sign-in does not re-apply a stale choice.
    expect(localStorage.getItem("inventari-language-choice")).toBeNull();
  });

  it("writes the pre-login choice back to the account", async () => {
    // Surviving the session is half of it; without the write-back the next
    // sign-in would hand back the account's old preference again.
    const { authApi } = await import("../lib/api/auth");
    const spy = vi.spyOn(authApi, "updateLanguage");
    rememberLanguageChoice("de");

    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    expect(spy).toHaveBeenCalledWith("de");
    spy.mockRestore();
  });

  it("does not write back when the choice already matches the account", async () => {
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "1",
          email: "test@example.com",
          full_name: "Test User",
          preferred_language: "pl",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
    );
    const { authApi } = await import("../lib/api/auth");
    const spy = vi.spyOn(authApi, "updateLanguage");
    rememberLanguageChoice("pl");

    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    expect(spy).not.toHaveBeenCalled();
    expect(i18n.language).toBe("pl");
    spy.mockRestore();
  });

  it("keeps the account's language when nothing was picked", async () => {
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "1",
          email: "test@example.com",
          full_name: "Test User",
          preferred_language: "de",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    expect(i18n.language).toBe("de");
  });

  it("sends the UI language with a registration request", async () => {
    // the request form has no language picker — the language the UI
    // already speaks is the choice, otherwise the account defaults to en/USD.
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    let received: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/auth/registration-request", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ message: "ok" });
      }),
    );
    await i18n.changeLanguage("pl");

    await act(async () => {
      await useAuthStore
        .getState()
        .requestRegistration("new@example.com", "New User");
    });

    expect(received).toMatchObject({
      email: "new@example.com",
      full_name: "New User",
      preferred_language: "pl",
    });
  });

  it("signs in even when the language preference cannot be saved, and says so in the log", async () => {
    const { authApi } = await import("../lib/api/auth");
    const { logger } = await import("../utils/logger");
    vi.spyOn(authApi, "updateLanguage").mockRejectedValue(new Error("offline"));
    const logged = vi.spyOn(logger, "error").mockImplementation(() => {});
    rememberLanguageChoice("de");

    await act(async () => {
      await useAuthStore.getState().login("test@example.com", "password");
    });

    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(i18n.language).toBe("de");
    await vi.waitFor(() =>
      expect(logged).toHaveBeenCalledWith(
        "Failed to save language preference:",
        expect.any(Error),
      ),
    );
    vi.restoreAllMocks();
  });

  it("sends the UI language with a registration and with its completion", async () => {
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    const received: Record<string, Record<string, unknown>> = {};
    server.use(
      http.post("/api/v1/auth/register", async ({ request }) => {
        received.register = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "u1" });
      }),
      http.post("/api/v1/auth/register-complete", async ({ request }) => {
        received.complete = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "u1" });
      }),
    );
    await i18n.changeLanguage("de");

    await act(async () => {
      await useAuthStore
        .getState()
        .register("new@example.com", "pw-12345678", "New User", "INVITE1");
      await useAuthStore
        .getState()
        .completeRegistration("tok-1", "pw-12345678", "New User");
    });

    expect(received.register).toMatchObject({
      email: "new@example.com",
      full_name: "New User",
      invite_code: "INVITE1",
      preferred_language: "de",
    });
    expect(received.complete).toMatchObject({
      token: "tok-1",
      full_name: "New User",
      preferred_language: "de",
    });
  });

  it("should logout successfully", async () => {
    // Setup logged in state
    act(() => {
      useAuthStore.setState({
        user: {
          is_blocked: false,
          is_superuser: false,
          permissions: [],
          is_active: true,
          id: "1",
          email: "test@example.com",
          full_name: "Test User",
          preferred_language: "en",
          role: "user",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        isAuthenticated: true,
      });
    });
    tokenStore.set("some_token");

    await act(async () => {
      await useAuthStore.getState().logout();
    });

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(tokenStore.get()).toBeNull();
  });

  it("logout forgets the scanner's remembered context", async () => {
    // The scan context outlived the identity that set it: a shared device
    // handed to a colleague kept scanning into the previous holder's shelf,
    // and the same account in another organization inherited a location id
    // from the old one. The remembered context is a convenience for the
    // session's owner, so it leaves with the session.
    useScanStore.getState().setStorageContext({
      id: "loc-1",
      name: "Server Rack B",
      icon: "Server",
    });
    useScanStore.getState().setLastUsed("loc-1", "cat-1");
    expect(useScanStore.getState().storageContext).not.toBeNull();

    await act(async () => {
      await useAuthStore.getState().logout();
    });

    const scan = useScanStore.getState();
    expect(scan.storageContext).toBeNull();
    expect(scan.lastStorageId).toBeNull();
    expect(scan.lastCategoryId).toBeNull();
  });

  it("logout takes the recently-visited list with it", async () => {
    // Its own docstring said "on logout: call clearRecentItems(userId)" and
    // nobody did, so the list of what the previous holder had opened stayed
    // in the browser for whoever logged in next. Same reasoning as the scan
    // context above, same teardown.
    act(() => {
      useAuthStore.setState({
        user: {
          is_blocked: false,
          is_superuser: false,
          permissions: [],
          is_active: true,
          id: "user-1",
          email: "test@example.com",
          full_name: "Test User",
          preferred_language: "en",
          role: "user",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        isAuthenticated: true,
      });
    });
    addRecentItem(
      {
        id: "item-1",
        title: "Server Rack B",
        module: "inventory",
        path: "/inventory/items/item-1",
        timestamp: Date.now(),
      },
      "user-1",
      "org-1",
    );
    expect(getRecentItems("user-1", "org-1")).toHaveLength(1);

    await act(async () => {
      await useAuthStore.getState().logout();
    });

    expect(getRecentItems("user-1", "org-1")).toHaveLength(0);
  });

  it("should check auth and set user if token exists", async () => {
    tokenStore.set("valid_token");

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.user?.email).toBe("test@example.com");
  });

  it("should set isAuthenticated to false if checkAuth fails", async () => {
    tokenStore.set("invalid_token");

    // Mock API failure for this test
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get("/api/v1/auth/me", () => {
        return new HttpResponse(null, { status: 401 });
      }),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(tokenStore.get()).toBeNull();
    // A 401 is an answer: the session really is over, so the shell may send
    // the reader to the sign-in form.
    expect(state.authUnavailable).toBe(false);
  });

  it("keeps the session when /auth/me answers 500", async () => {
    // A backend that is down is not a signed-out user: clearing the token sent
    // the reader to a sign-in form that failed for the very same reason.
    tokenStore.set("valid_token");

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get(
        "/api/v1/auth/me",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.authUnavailable).toBe(true);
    expect(state.isLoading).toBe(false);
    expect(tokenStore.get()).toBe("valid_token");
  });

  it("keeps the session when /auth/me never reaches the server", async () => {
    tokenStore.set("valid_token");

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(http.get("/api/v1/auth/me", () => HttpResponse.error()));

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    expect(useAuthStore.getState().authUnavailable).toBe(true);
    expect(tokenStore.get()).toBe("valid_token");
  });

  it("keeps the outage standing while its retry is in flight", async () => {
    // The retry button lives on the outage screen, and what that screen
    // promises is that the reader's place — and the message on it — stays put.
    // Wiping the previous answer when the ask started is what swapped the
    // screen for the boot spinner for as long as the ask lasted.
    tokenStore.set("valid_token");

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(http.get("/api/v1/auth/me", () => HttpResponse.error()));

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });
    expect(useAuthStore.getState().authUnavailable).toBe(true);

    // The retry is under way and has not answered yet.
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.get("/api/v1/auth/me", async () => {
        await gate;
        return HttpResponse.json({
          id: "1",
          email: "test@example.com",
          full_name: "Test User",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }),
    );

    const pending = useAuthStore.getState().checkAuth();
    try {
      expect(useAuthStore.getState().isLoading).toBe(true);
      expect(useAuthStore.getState().authUnavailable).toBe(true);
    } finally {
      // Let the ask finish either way: a checkAuth left in flight holds the
      // module-level promise that every later test in this file awaits.
      release();
      await act(async () => {
        await pending;
      });
    }
    // An answer arrived, so the outage is over — the flag does not outlive it.
    expect(useAuthStore.getState().authUnavailable).toBe(false);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("separates an unavailable backend from a spent session on refresh", async () => {
    // No access token, so checkAuth goes through /auth/refresh first — the
    // same distinction has to hold there.
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.post(
        "/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 503 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    expect(useAuthStore.getState().authUnavailable).toBe(true);

    server.use(
      http.post(
        "/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 401 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.authUnavailable).toBe(false);
    expect(state.isAuthenticated).toBe(false);
  });

  it("a refresh that answers 204 is a visitor with no session, not an outage", async () => {
    // The endpoint answers "no session" with No Content, so the boot probe
    // of a visitor who has never signed in is an ordinary answer — not a
    // refusal the browser would log as an error on every load.
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.post(
        "/api/v1/auth/refresh",
        () => new HttpResponse(null, { status: 204 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.isLoading).toBe(false);
    expect(state.isAuthenticated).toBe(false);
    expect(state.authUnavailable).toBe(false);
    expect(tokenStore.get()).toBeNull();
  });
});

describe("the retry keeps the outage's promise", () => {
  it("holds the gate closed while the retry is asking", async () => {
    // After a failed boot check there is no token and the shell shows the
    // outage. Clicking retry used to wipe authUnavailable before it asked
    // again — and for the whole length of the ask the state read "signed
    // out, no outage, nothing loading", which is exactly the state that
    // sends the reader to the sign-in form.
    act(() => {
      useAuthStore.setState({
        isAuthenticated: false,
        isLoading: false,
        authUnavailable: true,
        user: null,
      });
    });
    tokenStore.clear();

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post("/api/v1/auth/refresh", async () => {
        await held;
        return HttpResponse.error();
      }),
    );

    let checkPromise!: Promise<void>;
    try {
      act(() => {
        checkPromise = useAuthStore.getState().checkAuth();
      });

      // Synchronously after the click, mid-ask: the route gate reads
      // isLoading first, so holding it closed keeps the reader on the
      // outage screen instead of the sign-in form.
      const mid = useAuthStore.getState();
      expect(mid.isLoading).toBe(true);
      expect(mid.isAuthenticated).toBe(false);
    } finally {
      // The held request must never outlive the test — a pending axios
      // call stalls the next test's identical request.
      release();
    }
    await act(async () => {
      await checkPromise;
    });

    const after = useAuthStore.getState();
    expect(after.authUnavailable).toBe(true);
    expect(after.isAuthenticated).toBe(false);
  });

  it("a refresh refusal still ends the session", async () => {
    act(() => {
      useAuthStore.setState({
        isAuthenticated: false,
        isLoading: false,
        authUnavailable: true,
        user: null,
      });
    });
    tokenStore.clear();

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.post("/api/v1/auth/refresh", () =>
        HttpResponse.json({ detail: "bad cookie" }, { status: 400 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    // The server answered and refused: the session is over, the sign-in
    // form is the way on, and the outage screen must not hold the reader.
    const state = useAuthStore.getState();
    expect(state.authUnavailable).toBe(false);
    expect(state.isAuthenticated).toBe(false);
  });

  it("a 401 during a retry ends the session and drops the outage", async () => {
    // The retry runs with the outage standing — the flag is only cleared
    // when the ask answers. A refusal is an answer: leaving the flag up
    // keeps the reader on a screen claiming the server never replied, one
    // dead click away from the sign-in form this answer is calling for.
    tokenStore.set("expired-token");
    act(() => {
      useAuthStore.setState({
        isAuthenticated: true,
        isLoading: false,
        authUnavailable: true,
        user: null,
      });
    });

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.get(
        "/api/v1/auth/me",
        () => new HttpResponse(null, { status: 401 }),
      ),
    );

    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    const state = useAuthStore.getState();
    expect(state.authUnavailable).toBe(false);
    expect(state.isAuthenticated).toBe(false);
    expect(tokenStore.get()).toBeNull();
  });
});

describe("the remembered pick belongs to whoever made it", () => {
  const person = (id: string, organization_name: string) => ({
    id,
    email: `${id}@example.com`,
    full_name: id,
    organization_name,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  /** Who `GET /auth/me` says is signed in from here on. */
  const answerAs = async (user: ReturnType<typeof person>) => {
    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(http.get("/api/v1/auth/me", () => HttpResponse.json(user)));
  };

  const signInAs = async (user: ReturnType<typeof person>) => {
    await answerAs(user);
    await act(async () => {
      await useAuthStore.getState().login(user.email, "password");
    });
  };

  const rememberAPick = () => {
    useScanStore.getState().setStorageContext({
      id: "loc-old",
      name: "Fridge A",
      icon: "Snowflake",
    });
    useScanStore.getState().setLastUsed("loc-old", "cat-old");
    useFormMemoryStore
      .getState()
      .setLastItem({ location_id: "loc-old", category_id: "cat-old" });
  };

  const expectNothingRemembered = () => {
    const scan = useScanStore.getState();
    expect(scan.storageContext).toBeNull();
    expect(scan.lastStorageId).toBeNull();
    expect(scan.lastCategoryId).toBeNull();
    expect(useFormMemoryStore.getState().lastItem).toBeNull();
  };

  /** A page load: nothing in memory but what the device stored. */
  const reload = () => {
    tokenStore.clear();
    act(() => {
      useAuthStore.setState({ user: null, isAuthenticated: false });
    });
  };

  beforeEach(() => {
    reload();
    useScanStore.getState().clear();
    useFormMemoryStore.getState().clear();
  });

  it("does not follow a page load into the next demo organization", async () => {
    // The door the demo's visitors came through. The nightly reset deletes
    // the account under the tab; the next load asks for a session, the
    // refresh is refused before any user is known, and the visitor walks
    // through the demo button into a new organization. No sign-out ran on
    // that road, so the first scan opened on a place from the deleted one.
    await signInAs(person("visitor-1", "Demo"));
    rememberAPick();

    reload();
    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });
    expect(useAuthStore.getState().isAuthenticated).toBe(false);

    const { server } = await import("../test/mocks/server");
    const { http, HttpResponse } = await import("msw");
    server.use(
      http.post("/api/v1/demo/sandbox", () =>
        HttpResponse.json({ access_token: "t", token_type: "bearer" }),
      ),
    );
    await answerAs(person("visitor-2", "Demo"));
    await act(async () => {
      await useAuthStore.getState().openDemoSandbox();
    });

    expect(useAuthStore.getState().user?.id).toBe("visitor-2");
    expectNothingRemembered();
  });

  it("does not cross to the next account on the same device", async () => {
    await signInAs(person("anna", "Acme"));
    rememberAPick();

    reload();
    await signInAs(person("ben", "Acme"));

    expectNothingRemembered();
  });

  it("does not cross to another organization of the same account", async () => {
    await signInAs(person("anna", "Acme"));
    rememberAPick();

    await answerAs(person("anna", "Globex"));
    reload();
    tokenStore.set("still-signed-in");
    await act(async () => {
      await useAuthStore.getState().checkAuth();
    });

    expect(useAuthStore.getState().user?.organization_name).toBe("Globex");
    expectNothingRemembered();
  });

  it("is still there when the same person comes back", async () => {
    // A convenience worth keeping: a reload is not a change of hands.
    await signInAs(person("anna", "Acme"));
    rememberAPick();

    reload();
    await signInAs(person("anna", "Acme"));

    expect(useScanStore.getState().lastStorageId).toBe("loc-old");
    expect(useScanStore.getState().lastCategoryId).toBe("cat-old");
    expect(useFormMemoryStore.getState().lastItem).not.toBeNull();
  });
});
