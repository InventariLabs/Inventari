import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { toast } from "sonner";
import ResetPasswordPage from "./ResetPasswordPage";
import { authApi } from "@/lib/api/auth";
import { useAuthStore } from "@/store/authStore";
import type { AuthState } from "@/store/authStore";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/auth", () => ({
  authApi: { confirmPasswordReset: vi.fn(), checkPasswordReset: vi.fn() },
}));

let mounted: { unmount: () => void } | undefined;

const refusal = (status: number) =>
  Object.assign(new Error(`status ${status}`), {
    isAxiosError: true,
    response: { status, data: {} },
  });

function renderPage() {
  mounted = render(
    <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
      <Routes>
        <Route path="/reset-password/:token" element={<ResetPasswordPage />} />
      </Routes>
    </MemoryRouter>,
  );
  return mounted;
}

function fill(password: string, confirm = password) {
  // Prefix match: the required star renders inside the label as an
  // aria-hidden sibling, so the label's full text is "New password *".
  fireEvent.change(screen.getByLabelText(/^New password/), {
    target: { value: password },
  });
  fireEvent.change(screen.getByLabelText(/^Confirm password/), {
    target: { value: confirm },
  });
  fireEvent.click(screen.getByRole("button", { name: "Set new password" }));
}

describe("ResetPasswordPage", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    vi.mocked(authApi.checkPasswordReset).mockResolvedValue(undefined);
    renderPage();
    // The form appears once the link has been checked.
    await screen.findByLabelText(/^New password/);
  });

  it("says a session is live when the reader is already signed in", () => {
    expect(screen.queryByTestId("signed-in-notice")).toBeNull();
    act(() =>
      useAuthStore.setState({
        user: { email: "tomas@example.com" } as AuthState["user"],
        isAuthenticated: true,
      }),
    );
    expect(screen.getByTestId("signed-in-notice")).toBeInTheDocument();
    act(() => useAuthStore.setState({ user: null, isAuthenticated: false }));
  });

  it("does not offer to send a reset link — the link is what got us here", () => {
    expect(
      screen.queryByRole("button", { name: /Send reset link/i }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: "Set new password" }),
    ).toBeInTheDocument();
  });

  it("states the password rules before anything is typed", () => {
    expect(screen.getByTestId("password-rules")).toBeInTheDocument();
    expect(screen.getByTestId("password-rule-uppercase")).toHaveTextContent(
      "an uppercase letter",
    );
    expect(screen.getByTestId("password-rule-digit")).toHaveTextContent(
      "a digit",
    );
    expect(screen.getByTestId("password-rule-maxBytes")).toHaveTextContent(
      "at most 72 bytes",
    );
  });

  it("names the byte rule a long password breaks instead of sending it", async () => {
    // 73 bytes in UTF-8: 35 two-byte letters plus 'Aa1' — every character
    // rule passes, only the bcrypt byte ceiling breaks.
    fill("Ą".repeat(35) + "Aa1");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Password may be at most 72 bytes long.",
      ),
    );
    expect(authApi.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it("names the rule a password breaks instead of calling it invalid", async () => {
    fill("lowercase1");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Password must contain an uppercase letter.",
      ),
    );
    expect(authApi.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it("rejects a password with no digit", async () => {
    fill("NoDigitsHere");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Password must contain a digit.",
      ),
    );
    expect(authApi.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it("submits a password that meets every rule", async () => {
    vi.mocked(authApi.confirmPasswordReset).mockResolvedValue(undefined);
    fill("GoodPass1");

    await waitFor(() =>
      expect(authApi.confirmPasswordReset).toHaveBeenCalledWith(
        "tok-1",
        "GoodPass1",
      ),
    );
  });

  it("replaces the form with a refusal when the link is spent", async () => {
    // The refusal used to be a toast while the form stayed up, asking for a
    // password the dead link can never save.
    vi.mocked(authApi.confirmPasswordReset).mockRejectedValue(refusal(400));
    fill("GoodPass1");

    expect(await screen.findByTestId("reset-invalid-link")).toBeInTheDocument();
    expect(
      screen.getByText("Invalid or expired reset link."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Request a fresh reset link." }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/^New password/)).not.toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
    expect(
      screen.getByRole("link", { name: /back to login/i }),
    ).toBeInTheDocument();
  });

  it("keeps the form and says the request failed when the server broke", async () => {
    vi.mocked(authApi.confirmPasswordReset).mockRejectedValue(refusal(500));
    fill("GoodPass1");

    expect(
      await screen.findByTestId("reset-request-failed"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("reset-invalid-link")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^New password/)).toBeInTheDocument();
  });

  it("keeps the form when saving is refused for too many attempts, and says so", async () => {
    // A 429 refuses the pace of the requests, not the token: the link was
    // never used, and calling it dead sent the reader to ask for another.
    vi.mocked(authApi.confirmPasswordReset).mockRejectedValue(refusal(429));
    fill("GoodPass1");

    expect(await screen.findByTestId("reset-request-failed")).toHaveTextContent(
      /Too many attempts.*Your link has not been used/,
    );
    expect(screen.queryByTestId("reset-invalid-link")).not.toBeInTheDocument();
    expect(screen.getByLabelText(/^New password/)).toBeInTheDocument();
  });

  it("gives the same refusal when the URL carried no token at all", async () => {
    mounted?.unmount();
    vi.mocked(authApi.checkPasswordReset).mockClear();
    render(
      <MemoryRouter initialEntries={["/reset-password"]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("reset-invalid-link")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^New password/)).not.toBeInTheDocument();
    expect(authApi.checkPasswordReset).not.toHaveBeenCalled();
  });
});

describe("ResetPasswordPage — a link that is already dead", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the refusal on arrival, without the password form, and links to a fresh request", async () => {
    vi.mocked(authApi.checkPasswordReset).mockRejectedValue(refusal(400));
    render(
      <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
        <Routes>
          <Route
            path="/reset-password/:token"
            element={<ResetPasswordPage />}
          />
          <Route path="/forgot-password" element={<div>FORGOT_SCREEN</div>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("reset-invalid-link")).toBeInTheDocument();
    expect(authApi.checkPasswordReset).toHaveBeenCalledWith("tok-1");
    expect(screen.queryByLabelText(/^New password/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Set new password" }),
    ).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("link", { name: "Request a fresh reset link." }),
    );
    expect(await screen.findByText("FORGOT_SCREEN")).toBeInTheDocument();
  });

  it("keeps the form when the check is refused for too many attempts", async () => {
    vi.mocked(authApi.checkPasswordReset).mockRejectedValue(refusal(429));
    render(
      <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
        <Routes>
          <Route
            path="/reset-password/:token"
            element={<ResetPasswordPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText(/^New password/)).toBeInTheDocument();
    expect(screen.queryByTestId("reset-invalid-link")).not.toBeInTheDocument();
  });

  it("says the link is being checked while the answer is on its way", () => {
    vi.mocked(authApi.checkPasswordReset).mockReturnValue(
      new Promise<void>(() => {}),
    );
    render(
      <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
        <Routes>
          <Route
            path="/reset-password/:token"
            element={<ResetPasswordPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    // On screen, and in a live region a screen reader announces.
    expect(screen.getByRole("status")).toHaveTextContent(
      "Checking your reset link…",
    );
    expect(screen.queryByLabelText(/^New password/)).not.toBeInTheDocument();
  });

  it("keeps the form when the check itself could not be answered", async () => {
    vi.mocked(authApi.checkPasswordReset).mockRejectedValue(refusal(503));
    render(
      <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
        <Routes>
          <Route
            path="/reset-password/:token"
            element={<ResetPasswordPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByLabelText(/^New password/)).toBeInTheDocument();
    expect(screen.queryByTestId("reset-invalid-link")).not.toBeInTheDocument();
  });
});

describe("ResetPasswordPage — after the password is saved", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(authApi.checkPasswordReset).mockResolvedValue(undefined);
  });

  it("takes the reader to the login screen from the confirmation", async () => {
    vi.mocked(authApi.confirmPasswordReset).mockResolvedValue(undefined);
    render(
      <MemoryRouter initialEntries={["/reset-password/tok-1"]}>
        <Routes>
          <Route
            path="/reset-password/:token"
            element={<ResetPasswordPage />}
          />
          <Route path="/login" element={<div>LOGIN_SCREEN</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByLabelText(/^New password/);
    fill("GoodPass1");

    fireEvent.click(await screen.findByRole("button", { name: "Go to login" }));

    expect(await screen.findByText("LOGIN_SCREEN")).toBeInTheDocument();
  });
});
