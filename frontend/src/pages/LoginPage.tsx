import { useState, useEffect, useRef } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuthStore } from "@/store/authStore";
import { loginFailureKey } from "@/lib/loginFailure";
import {
  demoSandboxFailure,
  type DemoSandboxFailure,
} from "@/lib/demoSandboxFailure";
import { Mail, Lock, Inbox, KeyRound } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { useInitStatus } from "@/hooks/useInitStatus";
import { DemoEntry } from "@/components/demo/DemoEntry";
import { AuthLayout } from "./AuthLayout";

/**
 * Where a session started on this page lands: the account's home, or the
 * launcher for a demo visitor meeting their organization for the first time.
 * Module scope, not a ref — signing in rebuilds the router once the modules
 * are registered, and the page that comes back is a new instance.
 */
let landing = "/";

export default function LoginPage() {
  const { t, i18n } = useTranslation("auth");
  const { data: initStatus } = useInitStatus();
  // The link must name what /register actually offers: on an empty
  // installation it is the first-account bootstrap form ("Create new
  // account"), afterwards it is the access-request form. An approved
  // request creates an account with an organization of its own — never
  // a place in an existing one, which only an invitation admits (see
  // USER_GUIDE §1.1). Until the status answers, the request label
  // stays: initialized installations are the common case.
  const isUninitialized = initStatus?.is_initialized === false;
  // Set only on the public demo, where every message the instance would send
  // is caught in Mailpit beside it. The notice is the demo's own statement
  // that this address is not private and nothing leaves the stack.
  const demoInboxUrl = initStatus?.demo_inbox_url;
  const location = useLocation();
  // Sign-up and joining by invitation send the address just used along, so
  // the first sign-in does not ask for it again.
  const justRegistered = (location.state as { email?: unknown } | null)?.email;
  const [email, setEmail] = useState(
    typeof justRegistered === "string" ? justRegistered : "",
  );
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isOpeningDemo, setIsOpeningDemo] = useState(false);
  const [demoFailure, setDemoFailure] = useState<DemoSandboxFailure | null>(
    null,
  );
  const { login, openDemoSandbox, isAuthenticated, signOutReason } =
    useAuthStore();
  const navigate = useNavigate();
  // Set by PrivateRoute: the address the reader was sent away from. Only an
  // in-app path is followed, never a scheme or protocol-relative address.
  const asked = (location.state as { from?: unknown } | null)?.from;
  const from =
    typeof asked === "string" && /^\/(?![/\\])/.test(asked) ? asked : null;

  // Chosen once per page instance: StrictMode replays the effect on the same
  // instance after the module-scope landing was already spent, and the replay
  // must not send the visitor somewhere else than the first run did.
  const chosenTarget = useRef<string | null>(null);
  useEffect(() => {
    if (isAuthenticated) {
      chosenTarget.current ??= landing !== "/" ? landing : (from ?? "/");
      landing = "/";
      navigate(chosenTarget.current, { replace: true });
    }
  }, [isAuthenticated, navigate, from]);

  const handleTryDemo = async () => {
    setIsOpeningDemo(true);
    setDemoFailure(null);
    landing = "/launcher";
    try {
      await openDemoSandbox();
    } catch (error: unknown) {
      landing = "/";
      setDemoFailure(demoSandboxFailure(error));
    } finally {
      setIsOpeningDemo(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await login(email, password);
      // `t` is fixed to the language this render started in; signing in may
      // have switched the interface to the account's own.
      toast.success(i18n.t("loginSuccess", { ns: "auth" }));
      navigate(from ?? "/");
    } catch (error: unknown) {
      toast.error(t(loginFailureKey(error)));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout>
      <Card className="p-6 sm:p-8 border border-transparent shadow-lg">
        {initStatus?.is_demo && (
          <DemoEntry
            onTry={handleTryDemo}
            isOpening={isOpeningDemo}
            failure={demoFailure}
          />
        )}
        {/* The profile screen ends the session after a password change —
            the server has already refused every token minted before it — so
            the confirmation is said here, where the reader lands. */}
        {signOutReason === "passwordChanged" && (
          <div
            role="status"
            className="mb-6 flex items-start gap-2.5 rounded-lg bg-blue-50 px-3 py-2.5 text-sm text-on-info"
          >
            <KeyRound
              size={16}
              className="mt-0.5 shrink-0"
              aria-hidden="true"
            />
            <p>{t("login.passwordChanged")}</p>
          </div>
        )}
        <div className="mb-8 text-center sm:text-left">
          <h2 className="text-xl font-semibold text-on mb-3 leading-none">
            {t("login.title", { defaultValue: "Welcome back" })}
          </h2>
          {/* A demo takes no requests: there is no superuser to read one, the
              server refuses them, and the one-click sandbox above is the way
              in — so the page offers no door to a form that cannot answer. */}
          {!initStatus?.is_demo && (
            <p className="flex flex-wrap items-center gap-x-1 text-xs font-medium text-on-muted">
              {t("login.noAccount", { defaultValue: "No account yet?" })}
              <Link
                to="/register"
                className="inline-flex min-h-11 items-center md:min-h-0 text-primary-700 hover:text-primary-800 dark:text-primary-500 dark:hover:text-primary-500 transition-colors underline decoration-2 underline-offset-4"
              >
                {isUninitialized
                  ? t("createAccount")
                  : t("login.registerLink", { defaultValue: "Create one now" })}
              </Link>
            </p>
          )}
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <Input
            id="email"
            label={t("login.emailLabel", { defaultValue: "Email" })}
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            leftIcon={<Mail size={16} />}
            className="h-12 font-semibold"
          />
          <Input
            id="password"
            label={t("login.passwordLabel", { defaultValue: "Password" })}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            leftIcon={<Lock size={16} />}
            className="h-12 font-semibold"
          />

          <div className="flex justify-end">
            <Link
              to="/forgot-password"
              className="inline-flex min-h-11 items-center md:min-h-0 text-xs font-medium text-primary-700 hover:text-primary-800 dark:text-primary-500 dark:hover:text-primary-500 transition-colors underline decoration-2 underline-offset-4"
            >
              {t("login.forgotPassword", {
                defaultValue: "Forgot password?",
              })}
            </Link>
          </div>

          <div className="pt-2">
            <Button
              size="content"
              type="submit"
              disabled={isLoading}
              isLoading={isLoading}
              className="w-full h-12 text-base shadow-md shadow-accent-600/10 font-semibold tracking-tight"
            >
              {t("login.submitButton", { defaultValue: "Log in" })}
            </Button>
          </div>
        </form>

        {demoInboxUrl && (
          <div className="mt-6 flex items-start gap-2.5 rounded-lg bg-blue-50 px-3 py-2.5 text-xs text-on-info">
            <Inbox size={16} className="mt-px shrink-0" aria-hidden="true" />
            <p>
              {t("login.demoInboxNotice")}{" "}
              <a
                href={demoInboxUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium underline decoration-2 underline-offset-4"
              >
                {t("login.demoInboxLink")}
              </a>
            </p>
          </div>
        )}
      </Card>
    </AuthLayout>
  );
}
