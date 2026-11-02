import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import ForgotPasswordPage from "./ForgotPasswordPage";
import { authApi } from "@/lib/api/auth";
import { AxiosError } from "axios";
import { toast } from "sonner";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/auth", () => ({
  authApi: { requestPasswordReset: vi.fn() },
}));

const submit = () => {
  fireEvent.change(screen.getByLabelText(/Email/i), {
    target: { value: "someone@example.com" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Send reset link/i }));
};

describe("ForgotPasswordPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    render(
      <BrowserRouter>
        <ForgotPasswordPage />
      </BrowserRouter>,
    );
  });

  it("tells the reader to check their inbox when mail can leave", async () => {
    vi.mocked(authApi.requestPasswordReset).mockResolvedValue({
      status: "accepted",
      email_delivery_configured: true,
    });
    submit();
    expect(await screen.findByText(/Check your inbox/i)).toBeInTheDocument();
  });

  it("does not promise a letter the installation cannot send", async () => {
    // The backend logged "SMTP settings not configured. Email NOT sent." and
    // the screen said a link was on its way — a dead end with no way out.
    vi.mocked(authApi.requestPasswordReset).mockResolvedValue({
      status: "accepted",
      email_delivery_configured: false,
    });
    submit();
    await waitFor(() => {
      expect(screen.getByText(/does not send email/i)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Check your inbox/i)).not.toBeInTheDocument();
  });

  it("shows the server's refusal instead of a generic failure", async () => {
    vi.mocked(authApi.requestPasswordReset).mockRejectedValue(
      Object.assign(new AxiosError("Bad Request"), {
        response: {
          status: 400,
          data: {
            detail: {
              code: "VALIDATION_ERROR",
              message: "This is the public demo.",
            },
          },
        },
      }),
    );
    submit();
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("This is the public demo.");
    });
  });
});
