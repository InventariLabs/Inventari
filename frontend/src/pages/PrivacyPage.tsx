import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { QueryResult } from "@/components/ui/QueryResult";
import { useInitStatus } from "@/hooks/useInitStatus";
import type { InitStatus } from "@/lib/api/auth";
import { AuthLayout } from "./AuthLayout";

const LINK_CLASS =
  "font-medium text-primary-700 hover:text-primary-800 dark:text-primary-500 dark:hover:text-primary-500 underline decoration-2 underline-offset-4";

/**
 * What this installation keeps about the people who use it, who runs it, and
 * how to ask for a copy or for deletion.
 *
 * Public, beside the sign-in screen: the people it is for are often the ones
 * without an account. The text is the same for every install, so the one part
 * that differs — who runs it — comes from the server's configuration through
 * `init-status`, and an install that set nothing says so rather than naming
 * anyone. It speaks for this installation only; the README's Privacy section
 * is the statement for the software itself.
 */
export default function PrivacyPage() {
  const { t } = useTranslation("auth");
  const initStatus = useInitStatus();

  return (
    <AuthLayout>
      <Card className="p-6 sm:p-8 border border-transparent shadow-lg">
        <h2 className="text-xl font-semibold text-on mb-3 leading-none">
          {t("privacy.title")}
        </h2>
        <p className="mb-6 text-sm text-on-muted">{t("privacy.intro")}</p>
        <QueryResult query={initStatus}>
          {(status) => <PrivacyNotice status={status} />}
        </QueryResult>
        <Link
          to="/login"
          className={`mt-8 inline-flex min-h-11 items-center md:min-h-0 text-xs ${LINK_CLASS}`}
        >
          {t("privacy.backToSignIn")}
        </Link>
      </Card>
    </AuthLayout>
  );
}

function PrivacyNotice({ status }: { status: InitStatus }) {
  const { t } = useTranslation("auth");
  const isDemo = status.is_demo === true;

  return (
    <div className="space-y-6">
      {isDemo && (
        <Section title={t("privacy.demo.heading")}>
          <p>{t("privacy.demo.wiped")}</p>
          <p>{t("privacy.demo.inbox")}</p>
        </Section>
      )}
      <Section title={t("privacy.operator.heading")}>
        <Operator
          name={status.operator_name ?? null}
          contact={status.operator_contact ?? null}
        />
      </Section>
      <Section title={t("privacy.stored.heading")}>
        <p>{t("privacy.stored.account")}</p>
        <p>{t("privacy.stored.activity")}</p>
        <p>{t("privacy.stored.organization")}</p>
        <p>{t("privacy.stored.logs")}</p>
        <p>{t("privacy.stored.outside")}</p>
      </Section>
      <Section title={t("privacy.cookies.heading")}>
        <p>{t("privacy.cookies.session")}</p>
        {isDemo && <p>{t("privacy.cookies.demo")}</p>}
        <p>{t("privacy.cookies.local")}</p>
      </Section>
      <Section title={t("privacy.requests.heading")}>
        {isDemo && <p>{t("privacy.requests.demo")}</p>}
        <p>{t("privacy.requests.how")}</p>
        {!isDemo && <p>{t("privacy.requests.erasure")}</p>}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-on">{title}</h3>
      <div className="space-y-2 text-sm text-on-muted">{children}</div>
    </section>
  );
}

/**
 * Who runs it, as configured — and, for whatever is not, a plain "not
 * published" and the setting its administrator fills in.
 */
function Operator({
  name,
  contact,
}: {
  name: string | null;
  contact: string | null;
}) {
  const { t } = useTranslation("auth");

  return (
    <>
      <p>
        {name
          ? t("privacy.operator.name", { name })
          : t("privacy.operator.noName")}
      </p>
      <p>
        {contact ? (
          <>
            {t("privacy.operator.contact")} <Contact value={contact} />
          </>
        ) : (
          t("privacy.operator.noContact")
        )}
      </p>
      {(!name || !contact) && (
        <p className="text-xs">{t("privacy.operator.setupHint")}</p>
      )}
    </>
  );
}

/**
 * The contact as a link when it is one: a web address opens, an email address
 * starts a message. Anything else is shown as written — the value comes from
 * configuration, and no other scheme is put into an `href`.
 */
function Contact({ value }: { value: string }) {
  if (/^https?:\/\//i.test(value)) {
    return (
      <a
        href={value}
        target="_blank"
        rel="noopener noreferrer"
        className={LINK_CLASS}
      >
        {value}
      </a>
    );
  }
  if (/^[^\s@]+@[^\s@]+$/.test(value)) {
    return (
      <a href={`mailto:${value}`} className={LINK_CLASS}>
        {value}
      </a>
    );
  }
  return <span className="font-medium text-on">{value}</span>;
}
