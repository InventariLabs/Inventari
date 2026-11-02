import axios from "axios";
import { api, getEveryPage, tokenStore } from "./client";
import type { components } from "@/types/api-generated";
import type {
  AuthTokens,
  LoginCredentials,
  RegisterData,
  User,
  RegistrationRequest,
  RegistrationCompleteData,
} from "@/types";

export interface PasswordResetRequestResult {
  status: string;
  /** Whether this installation can send mail at all. */
  email_delivery_configured: boolean;
}

/**
 * What an unauthenticated boot learns about the installation: whether anyone
 * has registered yet, and — on the public demo — where its public mail inbox
 * is, so the sign-in screen can point a visitor at it. Generated type; the
 * field is documented on the backend schema.
 */
export type InitStatus = components["schemas"]["InitStatusResponse"];

export const authApi = {
  login: async (credentials: LoginCredentials): Promise<AuthTokens> => {
    const formData = new FormData();
    formData.append("username", credentials.username);
    formData.append("password", credentials.password);
    const response = await api.post<AuthTokens>("/auth/login", formData, {});
    return response.data;
  },

  /**
   * The public demo's one-click sign-in: an organization of the visitor's
   * own, the same one again from this browser, or a new one with `fresh`.
   * A new sandbox's account takes the language the visitor is reading in.
   */
  openDemoSandbox: async (
    fresh: boolean,
    preferredLanguage: string,
  ): Promise<AuthTokens> => {
    const response = await api.post<AuthTokens>("/demo/sandbox", {
      fresh,
      preferred_language: preferredLanguage,
    });
    return response.data;
  },

  register: async (data: RegisterData): Promise<User> => {
    const response = await api.post<User>("/auth/register", data);
    return response.data;
  },

  requestRegistration: async (data: {
    email: string;
    full_name?: string;
    invite_code?: string;
    preferred_language?: string;
  }): Promise<{ message: string }> => {
    const response = await api.post("/auth/registration-request", data);
    return response.data;
  },

  getRegistrationRequests: async (): Promise<RegistrationRequest[]> => {
    return getEveryPage<RegistrationRequest>("/auth/registration-requests");
  },

  approveRegistrationRequest: async (
    requestId: string,
  ): Promise<{
    message: string;
    registration_token: string;
    registration_link: string;
    email_sent: boolean;
  }> => {
    const response = await api.post(
      `/auth/registration-requests/${requestId}/approve`,
    );
    return response.data;
  },

  rejectRegistrationRequest: async (
    requestId: string,
  ): Promise<{ message: string }> => {
    const response = await api.post(
      `/auth/registration-requests/${requestId}/reject`,
    );
    return response.data;
  },

  /** Whose account an approval link finishes — the address and name from the request. */
  getRegistrationLink: async (
    token: string,
  ): Promise<{ email: string; full_name: string | null }> => {
    const response = await api.get(
      `/auth/registration-link/${encodeURIComponent(token)}`,
    );
    return response.data;
  },

  completeRegistration: async (
    data: RegistrationCompleteData,
  ): Promise<User> => {
    const response = await api.post<User>("/auth/register-complete", data);
    return response.data;
  },

  getMe: async (): Promise<User> => {
    const response = await api.get<User>("/auth/me");
    return response.data;
  },

  getInitStatus: async (): Promise<InitStatus> => {
    const response = await api.get<InitStatus>("/auth/init-status");
    return response.data;
  },

  updateLanguage: async (language: string): Promise<User> => {
    const response = await api.post<User>("/auth/me/language", { language });
    return response.data;
  },

  /**
   * The signed-in person's own name, or their password. A new password
   * travels with the current one: the server refuses it otherwise. The answer
   * carries no permissions, so it never replaces what `getMe` returned.
   */
  updateMe: async (
    data: components["schemas"]["UserUpdate"],
  ): Promise<User> => {
    const response = await api.patch<User>("/auth/me", data);
    return response.data;
  },

  refresh: async (): Promise<AuthTokens | null> => {
    const response = await api.post<AuthTokens | null>("/auth/refresh");
    // 204 No Content is the endpoint's answer to "there is no session to
    // refresh" — the boot probe asks this of every visitor on every load,
    // and an ordinary answer must not reach the console as an error.
    return response.status === 204 ? null : response.data;
  },

  logout: async (): Promise<void> => {
    await api.post("/auth/logout");
    tokenStore.clear();
  },

  getVersion: async (): Promise<{
    version: string;
    details: Record<string, string> | null;
  }> => {
    const response = await axios.get("/api/");
    return response.data;
  },

  requestPasswordReset: async (
    email: string,
  ): Promise<PasswordResetRequestResult> => {
    // Always 202 — the endpoint never reveals whether the email is known. It
    // does say whether this installation can send mail at all, which is about
    // the installation and not about the address.
    const response = await api.post<PasswordResetRequestResult>(
      "/auth/password-reset/request",
      { email },
    );
    return response.data;
  },

  confirmPasswordReset: async (
    token: string,
    newPassword: string,
  ): Promise<void> => {
    await api.post("/auth/password-reset/confirm", {
      token,
      new_password: newPassword,
    });
  },
};
