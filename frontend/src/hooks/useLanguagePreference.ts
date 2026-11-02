import { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { authApi } from "@/lib/api/auth";
import { rememberLanguageChoice } from "@/i18n/languageChoice";
import { resolveLang, type Language } from "@/i18n/languages";
import { logger } from "@/utils/logger";

/**
 * The interface language as one setting, wherever it is changed.
 *
 * The header selector and the profile screen both offer it. Read through
 * `useTranslation`, every holder re-renders when either one switches, so the
 * two cannot show different answers; and both save it the same way, to the
 * account when there is a session and to the pending sign-in choice when
 * there is none.
 */
export function useLanguagePreference(): {
  language: Language;
  changeLanguage: (next: Language) => Promise<void>;
} {
  const { i18n } = useTranslation();
  const language = resolveLang((i18n.language || "en").substring(0, 2));

  const changeLanguage = useCallback(
    async (next: Language) => {
      i18n.changeLanguage(next);
      try {
        await authApi.updateLanguage(next);
      } catch (error) {
        // Signed out (the selector is on the sign-in screen too), or the call
        // failed: hold the choice so the next sign-in adopts it instead of
        // replacing it with the account's stored preference.
        rememberLanguageChoice(next);
        logger.error("Failed to save language preference:", error);
      }
    },
    [i18n],
  );

  return { language, changeLanguage };
}
