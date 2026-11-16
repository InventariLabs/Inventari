import { useEffect } from "react";
import { useTranslation } from "react-i18next";

/**
 * The document's language follows the language on screen, whatever route it
 * is and whichever tree draws it.
 *
 * index.html ships `lang="en"` for whatever reads the document before React
 * mounts. A visitor meets a Polish form on /login, or a Polish attestation
 * page, before any shell exists — left alone, a screen reader pronounced it
 * in English phonetics and the browser offered to translate the page it was
 * already showing. Both trees (`App` and `PublicApp`) call this, so a route
 * moved from one to the other keeps the behaviour.
 */
export function useDocumentLanguage(): void {
  const { i18n } = useTranslation();
  useEffect(() => {
    document.documentElement.lang = i18n.language?.substring(0, 2) ?? "en";
  }, [i18n.language]);
}
