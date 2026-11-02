import { create } from "zustand";
import type { User } from "../types";
import { authApi } from "@/lib/api/auth";
import { tokenStore } from "../lib/api/client";
import { queryClient } from "@/lib/queryClient";
import i18n from "../i18n/config";
import { takeLanguageChoice } from "../i18n/languageChoice";
import { logger } from "@/utils/logger";
import { isServerRefusal } from "@/lib/errors";
import { useScanStore } from "./scanStore";
import { clearRecentItems } from "@/lib/recentItems";

let _checkAuthPromise: Promise<void> | null = null;

// The registration forms carry no language picker — the language the UI
// already speaks is the choice. Two-letter code, matching the
// backend's Language literal.
const currentLanguage = (): string => (i18n.language || "en").substring(0, 2);

/**
 * What follows a session the server has just issued, whichever way it was
 * asked for: the password form or the demo's one-click sandbox.
 */
async function enterSession(accessToken: string): Promise<User> {
  tokenStore.set(accessToken);
  // Drop any cached data from a previous session before fetching as the
  // new user — otherwise guards and pages would render stale org data.
  queryClient.clear();
  const user = await authApi.getMe();

  // A language picked on the sign-in screen wins over the account's stored
  // preference and is saved to the account — otherwise signing in threw the
  // choice away and switched the interface back.
  // Awaited, both times: catalogs load per language, so the switch is not
  // finished when the call returns. Whatever the caller says next — the
  // sign-in success toast, first of all — would otherwise be composed in the
  // language being left behind, and land next to a screen already in the new
  // one.
  const chosen = takeLanguageChoice();
  if (chosen && chosen !== user.preferred_language) {
    await i18n.changeLanguage(chosen);
    authApi.updateLanguage(chosen).catch((error) => {
      logger.error("Failed to save language preference:", error);
    });
  } else if (user.preferred_language) {
    await i18n.changeLanguage(user.preferred_language);
  }
  return user;
}

/** Why a session was ended on purpose, for the sign-in screen to say. */
export type SignOutReason = "passwordChanged";

export interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** The session check got no answer — the shell owes an outage, not the sign-in form. */
  authUnavailable: boolean;
  /**
   * Set by a sign-out the reader caused without asking for it, read by the
   * sign-in screen, cleared by the next sign-in. A sign-out without a reason
   * leaves it standing: the session refusals that follow a password change
   * end the same session a second time, and must not erase why.
   */
  signOutReason: SignOutReason | null;

  login: (email: string, password: string) => Promise<void>;
  /** The public demo's one-click sign-in; `fresh` starts over with a new organization. */
  openDemoSandbox: (fresh?: boolean) => Promise<void>;
  register: (
    email: string,
    password: string,
    fullName?: string,
    inviteCode?: string,
  ) => Promise<void>;
  requestRegistration: (email: string, fullName?: string) => Promise<void>;
  completeRegistration: (
    token: string,
    password: string,
    fullName?: string,
  ) => Promise<void>;
  logout: (reason?: SignOutReason) => Promise<void>;
  checkAuth: () => Promise<void>;
  /** Rename the signed-in person; every place showing them follows at once. */
  saveFullName: (fullName: string) => Promise<void>;
  /**
   * Replace the password, then end the session.
   *
   * The server invalidates every token minted before the change, this
   * session's included — and a token minted in the same second still counts
   * as older, so signing straight back in would be refused. The session is
   * therefore ended here, deliberately, with the reason the sign-in screen
   * gives back.
   */
  changePassword: (
    currentPassword: string,
    newPassword: string,
  ) => Promise<void>;
  /**
   * Re-read the identity — permissions included — without a page reload.
   *
   * `user.permissions` is filled at boot and read by every gate on every
   * screen, so an administrator who edited their own role kept the rights
   * they logged in with until the next reload. Quiet on failure: this is a
   * refresh of something already known, not a login, and a hiccup here must
   * not end a working session.
   */
  refreshUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  authUnavailable: false,
  signOutReason: null,

  login: async (email: string, password: string) => {
    const tokens = await authApi.login({ username: email, password });
    const user = await enterSession(tokens.access_token);
    set({
      user,
      isAuthenticated: true,
      authUnavailable: false,
      signOutReason: null,
    });
  },

  openDemoSandbox: async (fresh = false) => {
    const tokens = await authApi.openDemoSandbox(fresh, currentLanguage());
    const user = await enterSession(tokens.access_token);
    set({
      user,
      isAuthenticated: true,
      authUnavailable: false,
      signOutReason: null,
    });
  },

  register: async (
    email: string,
    password: string,
    fullName?: string,
    inviteCode?: string,
  ) => {
    await authApi.register({
      email,
      password,
      full_name: fullName,
      invite_code: inviteCode,
      preferred_language: currentLanguage(),
    });
  },

  requestRegistration: async (email: string, fullName?: string) => {
    await authApi.requestRegistration({
      email,
      full_name: fullName,
      preferred_language: currentLanguage(),
    });
  },

  completeRegistration: async (
    token: string,
    password: string,
    fullName?: string,
  ) => {
    await authApi.completeRegistration({
      token,
      password,
      full_name: fullName,
      preferred_language: currentLanguage(),
    });

    // After completion, we could log the user in automatically
    // But the backend doesn't return tokens from register-complete yet.
    // Let's just leave it as is, or we could redirect to login.
  },

  logout: async (reason?: SignOutReason) => {
    const leaving = get().user?.id;
    try {
      await authApi.logout();
    } catch {
      // Ignore errors on logout
    }
    tokenStore.clear();
    queryClient.clear();
    // The scanner's remembered context is a convenience for the session's
    // owner, not a durable setting: the next identity on this device must
    // not scan into the previous one's shelf.
    useScanStore.getState().clear();
    // And the list of what this identity had opened. Same reasoning, same
    // teardown: a shared device must not hand the next holder a list of the
    // previous one's records.
    if (leaving) clearRecentItems(leaving);
    set({
      user: null,
      isAuthenticated: false,
      authUnavailable: false,
      signOutReason: reason ?? get().signOutReason,
    });
  },

  saveFullName: async (fullName: string) => {
    const saved = await authApi.updateMe({ full_name: fullName });
    // Only the name is taken from the answer: it carries no permissions and
    // no organization name, and the gates on every screen read both.
    set((state) => ({
      user: state.user ? { ...state.user, full_name: saved.full_name } : null,
    }));
  },

  changePassword: async (currentPassword: string, newPassword: string) => {
    await authApi.updateMe({
      current_password: currentPassword,
      password: newPassword,
    });
    await get().logout("passwordChanged");
  },

  refreshUser: async () => {
    if (!get().isAuthenticated) return;
    try {
      const user = await authApi.getMe();
      set({ user });
    } catch {
      // Deliberately silent — see the interface comment.
    }
  },

  checkAuth: async () => {
    if (_checkAuthPromise) return _checkAuthPromise;

    _checkAuthPromise = (async () => {
      // The ask holds the route gate closed. What it no longer does is wipe
      // the previous answer: an outage stays standing while the retry runs,
      // so the screen that carries the retry button is still there when it is
      // pressed — clearing the flag here swapped that screen for the boot
      // spinner for as long as the ask lasted, which is the retry reporting
      // itself by taking its own message away. Every exit below sets the flag
      // from the answer it just got, so nothing stays stale.
      set({ isLoading: true });

      if (!tokenStore.get()) {
        try {
          const tokens = await authApi.refresh();
          if (!tokens) {
            // 204: there is no session to restore. The ordinary visitor —
            // not an outage, and not an error to log on every load.
            set({
              isLoading: false,
              isAuthenticated: false,
              authUnavailable: false,
            });
            return;
          }
          tokenStore.set(tokens.access_token);
        } catch (error) {
          set({
            isLoading: false,
            isAuthenticated: false,
            authUnavailable: !isServerRefusal(error),
          });
          return;
        }
      }

      try {
        const user = await authApi.getMe();

        if (user.preferred_language) {
          i18n.changeLanguage(user.preferred_language);
        }

        set({
          user,
          isAuthenticated: true,
          isLoading: false,
          authUnavailable: false,
        });
      } catch (error) {
        if (!isServerRefusal(error)) {
          // Keep the token — it may well still be good, and the retry has to be
          // able to use it.
          set({ isLoading: false, authUnavailable: true });
          return;
        }
        // Session over without an explicit logout — the same teardown, from
        // another door: the remembered scan context leaves with the
        // identity. The refusal is an answer, so the outage flag falls with
        // it: a retry that gets 4xx owes the reader the sign-in form, not a
        // screen claiming the server never replied.
        tokenStore.clear();
        useScanStore.getState().clear();
        const departed = get().user?.id;
        if (departed) clearRecentItems(departed);
        set({
          user: null,
          isAuthenticated: false,
          isLoading: false,
          authUnavailable: false,
        });
      }
    })();

    try {
      return await _checkAuthPromise;
    } finally {
      _checkAuthPromise = null;
    }
  },
}));

// What the forms remember about where things were put belongs to one person
// in one organization. Clearing it on the way out cannot promise that: a
// session can end with no user known to clear for — the load after a demo
// reset deleted the account gets its refresh refused and goes straight to the
// sign-in screen, and the demo button there opens a new organization on
// whatever the device still holds. So it is decided on the way in, here,
// where every door that names an identity passes. The name is in the key
// because the user record carries no organization id, and an account can
// change organization; a renamed organization costs one remembered shelf.
useAuthStore.subscribe(({ user }) => {
  if (user) {
    useScanStore
      .getState()
      .claimFor(`${user.id}:${user.organization_name ?? ""}`);
  }
});
