import { useTranslation } from "react-i18next";
import { Check, Circle } from "lucide-react";
import { checkPasswordRules, PASSWORD_RULES } from "@/lib/passwordPolicy";

interface Props {
  value: string;
}

/**
 * The password rules, shown before anything is typed and ticked off as the
 * reader types. A rule the reader only meets by failing a submit is a rule
 * the screen kept to itself.
 */
export function PasswordRules({ value }: Props) {
  const { t } = useTranslation("auth");
  const met = checkPasswordRules(value);

  return (
    <div
      className="rounded-xl bg-surface px-3 py-2.5"
      data-testid="password-rules"
    >
      <p className="text-xs font-medium text-on-secondary mb-1.5">
        {t("passwordPolicy.rulesTitle")}
      </p>
      <ul className="space-y-1">
        {PASSWORD_RULES.map((rule) => (
          <li
            key={rule}
            className={`flex items-center gap-1.5 text-xs ${
              met[rule] ? "text-accent-600 font-medium" : "text-on-muted"
            }`}
            data-testid={`password-rule-${rule}`}
          >
            {met[rule] ? (
              <Check size={13} aria-hidden />
            ) : (
              <Circle size={13} aria-hidden />
            )}
            <span>{t(`passwordPolicy.rules.${rule}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
