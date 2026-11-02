import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

type I18nModule = typeof import("@/i18n/config");
type AuthStoreModule = typeof import("./authStore");

let i18n: I18nModule["default"];
let useAuthStore: AuthStoreModule["useAuthStore"];

// The test setup imports module definitions, and one of them reaches the auth
// store before this file's mocks exist — a store loaded then keeps the real
// authApi. Re-evaluate both modules per test so the mock above is the one the
// store actually calls.
beforeEach(async () => {
  vi.resetModules();
  i18n = (await import("@/i18n/config")).default;
  ({ useAuthStore } = await import("./authStore"));
});

/**
 * Signing in applies the account's language, and catalogs load per language —
 * so `changeLanguage` is not finished when it returns. Whatever the caller did
 * next composed its text against a language that had been announced but not
 * loaded, and fell back to English: the shell came up in the account's
 * language and the "signed in" notification beside it in another.
 *
 * The unit suite loads every catalog up front, so the language a switch lands
 * on cannot be observed here. What can is the contract that fixes it — signing
 * in does not resolve until the switch has.
 */

const tokens = { access_token: "t", refresh_token: "r", token_type: "bearer" };

const user = {
  id: "u1",
  email: "admin@example.com",
  full_name: "Admin",
  role: "admin",
  preferred_language: "de",
  is_active: true,
  is_superuser: false,
};

vi.mock("@/lib/api/auth", () => ({
  authApi: {
    login: vi.fn(async () => tokens),
    getMe: vi.fn(async () => user),
    updateLanguage: vi.fn(async () => undefined),
  },
}));

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("signing in waits for the language it switches to", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("does not resolve while the catalogs are still loading", async () => {
    let arrive!: () => void;
    const loading = new Promise<void>((resolve) => {
      arrive = resolve;
    });
    vi.spyOn(i18n, "changeLanguage").mockReturnValue(
      loading as unknown as ReturnType<typeof i18n.changeLanguage>,
    );

    let signedIn = false;
    const login = useAuthStore
      .getState()
      .login("admin@example.com", "pw")
      .then(() => {
        signedIn = true;
      });

    await flush();
    expect(signedIn, "signing in resolved before its language did").toBe(false);

    arrive();
    await login;

    expect(signedIn).toBe(true);
  });

  it("asks for the account's language", async () => {
    const spy = vi
      .spyOn(i18n, "changeLanguage")
      .mockResolvedValue(
        undefined as unknown as Awaited<ReturnType<typeof i18n.changeLanguage>>,
      );

    await useAuthStore.getState().login("admin@example.com", "pw");

    expect(spy).toHaveBeenCalledWith("de");
  });
});
