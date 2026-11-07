import {
  act,
  render,
  screen,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  BrowserRouter,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RegisterPage from "./RegisterPage";
import { useAuthStore } from "@/store/authStore";
import type { AuthState } from "@/store/authStore";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { queryKeys } from "@/hooks/queries/keys";

// Mock API
vi.mock("@/lib/api", () => ({
  authApi: {
    getInitStatus: vi.fn().mockResolvedValue({ is_initialized: true }),
  },
}));

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

describe("RegisterPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: true }),
      ),
      http.get("/public/invitation/:code", () =>
        HttpResponse.json({ valid: true }),
      ),
    );
  });

  it("should render registration form", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/Full name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Email/i)).toBeInTheDocument();
    // Password should NOT be visible in request access mode
    expect(screen.queryByLabelText(/Password/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Request Access/i }),
    ).toBeInTheDocument();
  });

  it("should show link to login page", () => {
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("link", { name: /log in to existing account/i }),
    ).toBeInTheDocument();
  });

  it("should call requestRegistration and show success on success", async () => {
    const requestRegistrationMock = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      requestRegistration:
        requestRegistrationMock as unknown as AuthState["requestRegistration"],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Full name/i), {
      target: { value: "Test User" },
    });
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "test@example.com" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Request Access/i }));

    await waitFor(() => {
      expect(requestRegistrationMock).toHaveBeenCalledWith(
        "test@example.com",
        "Test User",
      );
    });
  });

  it("should show error toast on failure", async () => {
    const requestRegistrationMock = vi
      .fn()
      .mockRejectedValue(new Error("Request failed"));
    useAuthStore.setState({
      requestRegistration:
        requestRegistrationMock as unknown as AuthState["requestRegistration"],
    });

    const { toast } = await import("sonner");

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "existing@example.com" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Request Access/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalled();
    });
  });

  it("speaks the API's refusal instead of accusing the reader's data", async () => {
    // The invited colleague typed their own, correct address and heard
    // "check your data", because the catch block discarded whatever the API
    // said — an invitation that simply does not cover this address, a
    // server refusing for its own named reason.
    const apiShapedRefusal = {
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          code: "VALIDATION_ERROR",
          message: "Invalid organization invitation",
        },
      },
    };
    const registerMock = vi.fn().mockRejectedValue(apiShapedRefusal);
    useAuthStore.setState({
      register: registerMock as unknown as AuthState["register"],
    });

    const { toast } = await import("sonner");

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?invite=ABC123"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Full name/i), {
      target: { value: "Invited Colleague" },
    });
    fireEvent.change(screen.getByLabelText(/Email address/i), {
      target: { value: "kolega@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^Password/i), {
      target: { value: "Sup3r-secret" },
    });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "Sup3r-secret" },
    });

    fireEvent.click(
      screen.getByRole("button", { name: /Create new account/i }),
    );

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Invalid organization invitation",
      );
    });
    expect(toast.error).not.toHaveBeenCalledWith(
      "Failed to create account. Please check your data.",
    );
  });

  it("confirms an access request once, and says what happens next", async () => {
    // The card printed the headline again underneath itself, and its only
    // action was "Sign in" — offered to somebody whose account does not
    // exist until an administrator approves the request.
    const requestRegistrationMock = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      requestRegistration:
        requestRegistrationMock as unknown as AuthState["requestRegistration"],
    });

    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    fireEvent.change(screen.getByLabelText(/Full name/i), {
      target: { value: "Test User" },
    });
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "test@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Request Access/i }));

    const headline = await screen.findByRole("heading", {
      name: /administrator approval/i,
    });
    expect(headline).toBeInTheDocument();
    // The sentence the headline carries, and no second copy of it.
    expect(screen.getAllByText(/administrator approval/i)).toHaveLength(1);
    expect(
      screen.getByText(/we will email a link to test@example\.com/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
    // No toast repeats the headline: the card is the confirmation. (Other
    // cases in this file raise toasts, so this asks about the sentence.)
    expect(toast.success).not.toHaveBeenCalledWith(
      "Access request submitted. Please wait for administrator approval.",
    );
  });

  it("tells a requester their approved request creates an organization of its own", () => {
    // An approved request lands the account in its own empty organization,
    // not in the one the requester may have hoped to join — the request
    // form must say so up front, and point to invitations for joining.
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByText(/organization of its own/i)).toBeInTheDocument();
    expect(
      screen.getByText(/ask its administrator for an invitation/i),
    ).toBeInTheDocument();
  });

  it("keeps the own-organization explanation off the invitation form", () => {
    // The invite form does admit into the inviting organization; the
    // explanation belongs only to the request form.
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?invite=ABC123"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.queryByText(/organization of its own/i)).toBeNull();
  });

  it("names the organization and prefills the address of an invitation", async () => {
    server.use(
      http.get("/public/invitation/ABC123", () =>
        HttpResponse.json({
          valid: true,
          organization_name: "Acme Foods",
          inviter_name: "Ada Admin",
          role: "manager",
          invited_email: "nowa@example.com",
        }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?invite=ABC123"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Acme Foods/)).toHaveTextContent(
      /Ada Admin/,
    );
    await waitFor(() =>
      expect(screen.getByLabelText(/Email address/i)).toHaveValue(
        "nowa@example.com",
      ),
    );
  });

  it("names the invited role the way the rest of the product does", async () => {
    // The API answers with the key (`user`); "invited ... as user" named a
    // role that exists nowhere else — every other screen says Member.
    server.use(
      http.get("/public/invitation/ABC123", () =>
        HttpResponse.json({
          valid: true,
          organization_name: "Acme Foods",
          inviter_name: "Ada Admin",
          role: "user",
          invited_email: "nowa@example.com",
        }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?invite=ABC123"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const sentence = await screen.findByText(/Acme Foods/);
    expect(sentence).toHaveTextContent(/as Member\./);
    expect(sentence).not.toHaveTextContent(/as user/);
  });

  it("keeps a custom role's name as its author wrote it", async () => {
    server.use(
      http.get("/public/invitation/ABC123", () =>
        HttpResponse.json({
          valid: true,
          organization_name: "Acme Foods",
          inviter_name: "Ada Admin",
          role: "Shift lead",
          invited_email: "nowa@example.com",
        }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?invite=ABC123"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Acme Foods/)).toHaveTextContent(
      /as Shift lead\./,
    );
  });

  it("shows whose account an approval link finishes and prefills the name", async () => {
    server.use(
      http.get("/api/v1/auth/registration-link/tok1", () =>
        HttpResponse.json({ email: "jan@example.com", full_name: "Jan Link" }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?token=tok1"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/jan@example.com/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText(/Full name/i)).toHaveValue("Jan Link"),
    );
  });

  it("says whose session continues when a link is opened while another account is signed in", async () => {
    server.use(
      http.get("/api/v1/auth/registration-link/tok1", () =>
        HttpResponse.json({ email: "pia@example.com", full_name: "Pia" }),
      ),
    );
    const logout = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      user: { email: "tomas@example.com" } as AuthState["user"],
      isAuthenticated: true,
      logout: logout as unknown as AuthState["logout"],
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?token=tok1"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByText(/signed in as tomas@example\.com/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sign out first" }));
    expect(logout).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByLabelText(/Full name/i)).toHaveValue("Pia"),
    );
    act(() => useAuthStore.setState({ user: null, isAuthenticated: false }));
  });

  it("says a session is live on the plain request-access page too", async () => {
    useAuthStore.setState({
      user: { email: "tomas@example.com" } as AuthState["user"],
      isAuthenticated: true,
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("signed-in-notice")).toHaveTextContent(
      /signed in as tomas@example\.com/,
    );
    act(() => useAuthStore.setState({ user: null, isAuthenticated: false }));
  });

  it("shows no session notice when nobody is signed in", async () => {
    server.use(
      http.get("/api/v1/auth/registration-link/tok1", () =>
        HttpResponse.json({ email: "pia@example.com", full_name: "Pia" }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register?token=tok1"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await screen.findByText(/pia@example.com/);
    expect(screen.queryByText(/signed in as/)).toBeNull();
  });

  it("does not promise an e-mail on an installation that cannot send one", async () => {
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({
          is_initialized: true,
          email_delivery_configured: false,
        }),
      ),
    );
    useAuthStore.setState({
      requestRegistration: vi
        .fn()
        .mockResolvedValue(
          undefined,
        ) as unknown as AuthState["requestRegistration"],
    });
    render(
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <RegisterPage />
        </BrowserRouter>
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "a@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Request Access/i }));

    await screen.findByText(/Access request submitted/i);
    expect(await screen.findByText(/cannot send e-mail/i)).toBeInTheDocument();
  });
  it("stops offering first-account setup once the first account exists", async () => {
    let initialized = false;
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: initialized }),
      ),
    );
    useAuthStore.setState({
      register: vi.fn().mockImplementation(async () => {
        initialized = true;
      }) as unknown as AuthState["register"],
    });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register"]}>
          <RegisterPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const password = await screen.findByLabelText(/^Password/i);
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "first@example.com" },
    });
    fireEvent.change(password, { target: { value: "Str0ng!passphrase" } });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "Str0ng!passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() =>
      expect(
        queryClient.getQueryData<{ is_initialized: boolean }>(
          queryKeys.admin.initStatus,
        )?.is_initialized,
      ).toBe(true),
    );
  });
  it("signs the first account in and continues to the app, not the sign-in form", async () => {
    const login = vi.fn().mockResolvedValue(undefined);
    useAuthStore.setState({
      register: vi
        .fn()
        .mockResolvedValue(undefined) as unknown as AuthState["register"],
      login: login as unknown as AuthState["login"],
    });
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: false }),
      ),
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register"]}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/" element={<p>the app</p>} />
            <Route path="/login" element={<p>sign-in form</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const password = await screen.findByLabelText(/^Password/i);
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(password, { target: { value: "Str0ng!passphrase" } });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "Str0ng!passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    expect(await screen.findByText("the app")).toBeInTheDocument();
    expect(login).toHaveBeenCalledWith(
      "owner@example.com",
      "Str0ng!passphrase",
    );
    expect(screen.queryByText("sign-in form")).not.toBeInTheDocument();
  });
  it("falls back to the sign-in page, address filled in, when the new account cannot sign in yet", async () => {
    useAuthStore.setState({
      register: vi
        .fn()
        .mockResolvedValue(undefined) as unknown as AuthState["register"],
      login: vi
        .fn()
        .mockRejectedValue(
          new Error("refused"),
        ) as unknown as AuthState["login"],
    });
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: false }),
      ),
    );
    const SignInStub = () => (
      <p>
        sign-in for {(useLocation().state as { email?: string } | null)?.email}
      </p>
    );
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/register"]}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/login" element={<SignInStub />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const password = await screen.findByLabelText(/^Password/i);
    fireEvent.change(screen.getByLabelText(/Email/i), {
      target: { value: "owner@example.com" },
    });
    fireEvent.change(password, { target: { value: "Str0ng!passphrase" } });
    fireEvent.change(screen.getByLabelText(/Confirm password/i), {
      target: { value: "Str0ng!passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create/i }));

    expect(
      await screen.findByText("sign-in for owner@example.com"),
    ).toBeInTheDocument();
  });
});
