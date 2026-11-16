import { useEffect } from "react";

/** What the tab says when the page has no title of its own. */
const APP_TITLE = "Inventari";

/**
 * The tab, bookmark and history entry of a page: `<page> · Inventari`.
 *
 * A screen reader announces the document title on every navigation, and the
 * history menu lists nothing else; index.html's static `Inventari` made every
 * entry the same. Pass the text of the page's own heading, already in the
 * language on screen, and the title follows it when either changes.
 *
 * The title goes back to the plain name when the page unmounts, so a screen
 * that never sets one cannot inherit the last page's — the next page's effect
 * runs after this cleanup.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    document.title = `${title} · ${APP_TITLE}`;
    return () => {
      document.title = APP_TITLE;
    };
  }, [title]);
}
