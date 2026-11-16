import { useEffect } from "react";

/** What the tab says when the page has no title of its own. */
const APP_TITLE = "Inventari";

/** The titles of the mounted holders, oldest first; the newest one names the tab. */
const holders: { title: string }[] = [];

function paint(): void {
  const top = holders[holders.length - 1];
  document.title = top ? `${top.title} · ${APP_TITLE}` : APP_TITLE;
}

/**
 * The tab, bookmark and history entry of a page: `<page> · Inventari`.
 *
 * A screen reader announces the document title on every navigation, and the
 * history menu lists nothing else; index.html's static `Inventari` made every
 * entry the same. Pass the text of the page's own heading, already in the
 * language on screen, and the title follows it when either changes.
 *
 * Several holders can be mounted at once (the shell's page header and a
 * not-found block inside it, a lazily loaded page beside the one it replaces),
 * so each keeps its own entry: the newest names the tab, and when a holder
 * unmounts the one that is still mounted takes the tab back. The plain name
 * returns only when none is left, so a screen that sets no title cannot
 * inherit the last page's.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    const holder = { title };
    holders.push(holder);
    paint();
    return () => {
      holders.splice(holders.indexOf(holder), 1);
      paint();
    };
  }, [title]);
}
