import { useEffect, useRef } from "react";

/** What the tab says when the page has no title of its own. */
const APP_TITLE = "Inventari";

/** The titles of the mounted holders, oldest first; the newest one names the tab. */
const holders: { title: string | null }[] = [];

function paint(): void {
  const named = holders.filter((holder) => holder.title);
  const top = named[named.length - 1];
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
 * so each keeps its own entry: the one that mounted last and has a title
 * names the tab, whatever order their titles change in, and when a holder
 * unmounts the one that is still mounted takes the tab back. The plain name
 * returns only when none is left, so a screen that sets no title cannot
 * inherit the last page's.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  // One entry per mount: a re-titled holder keeps the place it took when it
  // mounted, so a language switch that re-titles two holders at once leaves
  // the inner one naming the tab.
  const holder = useRef<{ title: string | null }>({ title: null });
  useEffect(() => {
    const mine = holder.current;
    holders.push(mine);
    return () => {
      holders.splice(holders.indexOf(mine), 1);
      paint();
    };
  }, []);
  useEffect(() => {
    holder.current.title = title || null;
    paint();
  }, [title]);
}
