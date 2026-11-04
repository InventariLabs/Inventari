import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

const STORAGE_KEY = "inventari.scroll";
const KEPT_ENTRIES = 60;
// About two seconds at 60 fps: long enough for a list to fetch and paint,
// short enough not to fight a reader who has long since moved on.
const RESTORE_FRAMES = 120;

type Positions = Record<string, number>;

function readPositions(): Positions {
  try {
    return JSON.parse(sessionStorage.getItem(STORAGE_KEY) ?? "{}") as Positions;
  } catch {
    return {};
  }
}

function remember(entry: string, y: number) {
  try {
    const positions = readPositions();
    delete positions[entry];
    positions[entry] = Math.round(y);
    const kept = Object.entries(positions).slice(-KEPT_ENTRIES);
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(Object.fromEntries(kept)),
    );
  } catch {
    // Storage may be blocked; the position is a convenience.
  }
}

/**
 * Where the page is scrolled on each screen, for the whole app shell.
 *
 * The page scrolls as a whole and the shell outlives every route, so a new
 * screen used to open where the last one was scrolled: a product's name above
 * the fold, the journal's newest move out of sight.
 *
 * - A link or a button (PUSH, REPLACE) opens a screen at its top. Only a
 *   change of path counts — a filter written to the query string must not
 *   throw the reader to the top — and an address with a hash scrolls to its
 *   anchor instead.
 * - Going back (POP) returns to where the earlier entry was left. The browser
 *   cannot do it: it restores before the list has been fetched and painted,
 *   clamps to the short page it finds and gives up, so the position is kept
 *   here and applied for as long as the page is still growing to it.
 */
export function useRouteScroll() {
  const location = useLocation();
  const navigationType = useNavigationType();
  // The `key` of an entry is not unique to one address (the first entry of a
  // tab is always "default"), so the address is part of what names it.
  const entry = `${location.key}|${location.pathname}${location.search}`;
  const current = useRef(entry);
  const restoring = useRef(false);
  const shownPath = useRef<string | null>(null);
  const shownHash = useRef("");

  useEffect(() => {
    try {
      window.history.scrollRestoration = "manual";
    } catch {
      // Not every environment lets it be set.
    }
    const onScroll = () => {
      if (!restoring.current) remember(current.current, window.scrollY);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Before the new screen paints (and before the browser reports the scroll it
  // clamps to when the old one shrinks), so that report is filed under it.
  // A replaced entry (a filter written to the address) carries its position on.
  useLayoutEffect(() => {
    current.current = entry;
    if (navigationType === "REPLACE") remember(entry, window.scrollY);
  }, [entry, navigationType]);

  useEffect(() => {
    const first = shownPath.current === null;
    const pathChanged = !first && shownPath.current !== location.pathname;
    shownPath.current = location.pathname;
    // Leaving a section of the page (`#people`) for the page itself.
    const leftSection = shownHash.current !== "" && location.hash === "";
    shownHash.current = location.hash;

    if (navigationType !== "POP") {
      if ((pathChanged || leftSection) && !location.hash) window.scrollTo(0, 0);
      return;
    }
    if (location.hash) return;

    const target = readPositions()[entry] ?? 0;
    if (target <= 0) {
      if (!first) window.scrollTo(0, 0);
      return;
    }

    restoring.current = true;
    let frame = 0;
    let handle = 0;
    const stop = () => {
      restoring.current = false;
      cancelAnimationFrame(handle);
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchstart", stop);
      window.removeEventListener("keydown", stop);
    };
    const step = () => {
      const reachable =
        document.documentElement.scrollHeight - window.innerHeight;
      window.scrollTo(0, Math.min(target, Math.max(reachable, 0)));
      if (reachable >= target || ++frame >= RESTORE_FRAMES) stop();
      else handle = requestAnimationFrame(step);
    };
    window.addEventListener("wheel", stop, { passive: true });
    window.addEventListener("touchstart", stop, { passive: true });
    window.addEventListener("keydown", stop);
    step();
    return stop;
    // All of these change together, with the entry: one run per screen shown.
  }, [entry, navigationType, location.pathname, location.hash]);
}
