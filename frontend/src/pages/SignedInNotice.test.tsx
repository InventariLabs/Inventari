import { act, render, screen, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { SignedInNotice } from "./SignedInNotice";
import { useAuthStore } from "@/store/authStore";
import type { AuthState } from "@/store/authStore";

afterEach(() => {
  act(() => useAuthStore.setState({ user: null, isAuthenticated: false }));
});

const renderNotice = () =>
  render(
    <MemoryRouter>
      <SignedInNotice />
    </MemoryRouter>,
  );

describe("SignedInNotice", () => {
  it("says whose session is live and offers both ways on", () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      user: { email: "tomas@example.com" } as AuthState["user"],
      isAuthenticated: true,
      logout: logout as unknown as AuthState["logout"],
    });
    renderNotice();

    expect(screen.getByTestId("signed-in-notice")).toHaveTextContent(
      /signed in as tomas@example\.com/,
    );
    expect(
      screen.getByRole("link", { name: "Continue to Inventari" }),
    ).toHaveAttribute("href", "/");
    fireEvent.click(screen.getByRole("button", { name: "Sign out first" }));
    expect(logout).toHaveBeenCalled();
  });

  it("renders nothing when nobody is signed in", () => {
    renderNotice();
    expect(screen.queryByTestId("signed-in-notice")).toBeNull();
  });
});
