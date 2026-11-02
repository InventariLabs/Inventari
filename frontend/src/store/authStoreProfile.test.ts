import { act } from "react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { server } from "@/test/mocks/server";
import { tokenStore } from "../lib/api/client";
import type { User } from "../types";
import { useAuthStore } from "./authStore";

const SIGNED_IN: User = {
  id: "1",
  email: "anna@example.com",
  full_name: "Anna Nowak",
  role: "manager",
  is_active: true,
  is_superuser: false,
  is_blocked: false,
  permissions: ["items:read", "items:write"],
  organization_name: "Pantry & Co",
  preferred_language: "en",
};

function signIn() {
  act(() => {
    useAuthStore.setState({
      user: SIGNED_IN,
      isAuthenticated: true,
      isLoading: false,
      authUnavailable: false,
      signOutReason: null,
    });
  });
  tokenStore.set("a_session_token");
}

/** What PATCH /auth/me answers: the account row, without the permissions. */
function answerPatchWith(status: number, body: object) {
  const sent: unknown[] = [];
  server.use(
    http.patch("*/auth/me", async ({ request }) => {
      sent.push(await request.json());
      return HttpResponse.json(body, { status });
    }),
  );
  return sent;
}

describe("authStore — the person's own profile", () => {
  beforeEach(() => {
    signIn();
  });

  it("renames the person and keeps the permissions and organization the session was read with", async () => {
    const sent = answerPatchWith(200, {
      ...SIGNED_IN,
      full_name: "Anna Kowalska",
      permissions: [],
      organization_name: null,
    });

    await act(() => useAuthStore.getState().saveFullName("Anna Kowalska"));

    expect(sent).toEqual([{ full_name: "Anna Kowalska" }]);
    const user = useAuthStore.getState().user;
    expect(user?.full_name).toBe("Anna Kowalska");
    expect(user?.permissions).toEqual(["items:read", "items:write"]);
    expect(user?.organization_name).toBe("Pantry & Co");
  });

  it("ends the session after a password change and keeps the reason for the sign-in screen", async () => {
    const sent = answerPatchWith(200, SIGNED_IN);

    await act(() =>
      useAuthStore.getState().changePassword("OldPass123", "NewPass456"),
    );

    expect(sent).toEqual([
      { current_password: "OldPass123", password: "NewPass456" },
    ]);
    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(false);
    expect(state.user).toBeNull();
    expect(tokenStore.get()).toBeNull();
    expect(state.signOutReason).toBe("passwordChanged");
  });

  it("keeps the session when the server refuses the password change", async () => {
    answerPatchWith(400, {
      detail: {
        code: "VALIDATION_ERROR",
        message: "Current password is incorrect",
        field: "current_password",
      },
    });

    await expect(
      useAuthStore.getState().changePassword("Wrong123", "NewPass456"),
    ).rejects.toBeTruthy();

    const state = useAuthStore.getState();
    expect(state.isAuthenticated).toBe(true);
    expect(state.signOutReason).toBeNull();
  });

  it("does not let the refusals that follow a password change erase why the session ended", async () => {
    // The requests already in flight carry the old token; their 401 ends
    // the session a second time, through the plain logout.
    answerPatchWith(200, SIGNED_IN);
    await act(() =>
      useAuthStore.getState().changePassword("OldPass123", "NewPass456"),
    );

    await act(() => useAuthStore.getState().logout());

    expect(useAuthStore.getState().signOutReason).toBe("passwordChanged");
  });

  it("forgets the reason once the person signs in again", async () => {
    answerPatchWith(200, SIGNED_IN);
    await act(() =>
      useAuthStore.getState().changePassword("OldPass123", "NewPass456"),
    );

    await act(() =>
      useAuthStore.getState().login("anna@example.com", "NewPass456"),
    );

    expect(useAuthStore.getState().signOutReason).toBeNull();
  });
});
