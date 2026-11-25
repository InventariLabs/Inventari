import { useEffect, useRef } from "react";
import {
  useLocation,
  useNavigate,
  useNavigationType,
  type Location,
  type NavigateFunction,
} from "react-router-dom";
import { useReturnTarget } from "@/hooks/useReturnTarget";

const trimmed = (path: string) => path.replace(/\/+$/, "") || "/";

/**
 * The screen one level up inside a module: `/inventory/items/42` ->
 * `/inventory/items`. Never climbs out of the module — its root is the top —
 * and never lands on a path no screen answers: a path segment is not always a
 * screen (`/warehouse/documents/42` has no `/warehouse/documents` above it),
 * so it climbs past the empty ones and answers `null` when the module
 * registers no screen above this one at all.
 */
function parentWithinModule(
  pathname: string,
  basePath: string,
  routeExists: (path: string) => boolean,
): string | null {
  const base = trimmed(basePath);
  const inside = (path: string) => path === base || path.startsWith(`${base}/`);
  let parent = trimmed(pathname).split("/").slice(0, -1).join("/") || "/";
  while (inside(parent)) {
    if (routeExists(parent)) return parent;
    if (parent === base) break;
    parent = parent.split("/").slice(0, -1).join("/") || "/";
  }
  return null;
}

/**
 * Whether the history holds an earlier entry of this app to go back to.
 *
 * A `replace` hands the screen a fresh location `key` without adding an entry,
 * so the key alone cannot tell a screen reached by a link from one a person
 * opened in a new tab and then had replaced. The browser router counts its
 * entries in `history.state.idx`; that is the truth where it exists. Without
 * it (a memory router) the router's initial `"default"` key is all there is.
 */
export function hasHistoryToPop(location: Location): boolean {
  const idx: unknown = window.history.state?.idx;
  return typeof idx === "number" ? idx > 0 : location.key !== "default";
}

/**
 * Where `target` is, relative to this entry, when a screen sends the reader
 * to it: by popping when the entry just before is that screen — or when the
 * shell never saw the entry before (a reload) and the browser counts an
 * earlier one, which is then the screen the reader came from — so the history
 * does not grow a second copy of it; by replacing this entry otherwise.
 */
function goTo(
  navigate: NavigateFunction,
  location: Location,
  target: string,
  before: string | undefined,
): void {
  const targetPath = trimmed(target.split(/[?#]/)[0]);
  const popsToIt =
    before === undefined
      ? hasHistoryToPop(location)
      : trimmed(before) === targetPath;
  if (popsToIt) navigate(-1);
  else navigate(target, { replace: true });
}

/**
 * The path of the entry right before the current one, while the shell knows
 * it. The shell header and the screens under it both ask, so it lives at
 * module level: there is one shell per tab.
 */
let entryBefore: string | undefined;

/**
 * What the phone header's Back arrow does. A label that says Back promises
 * the previous screen, so:
 *
 * 1. a screen reached from another module's screen goes where that screen
 *    named (`useReturnTarget`) — by popping when the entry just before is that
 *    screen, so the history does not grow a second copy of it that would send
 *    the next Back round again;
 * 2. a module's root is the top, and leads home (the launcher);
 * 3. anywhere else it pops the history, like the browser button — the list
 *    with its filter and scroll position, not the launcher;
 * 4. a screen opened by a direct link has no history to pop, so it climbs to
 *    the nearest screen above it that the module registers (`routeExists`) —
 *    and home when it registers none, never to a path that renders nothing.
 */
export function useShellBack(
  basePath: string | undefined,
  homePath: string,
  routeExists: (path: string) => boolean = () => true,
): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  const navigationType = useNavigationType();
  const returnTarget = useReturnTarget();

  // The path of the entry right before this one, while it is known: a push
  // leaves the screen it came from there, a replace keeps what it had, and a
  // pop (a browser button, a reload) says nothing about it.
  const current = useRef({ key: location.key, path: location.pathname });
  const before = useRef<string | undefined>(undefined);
  useEffect(
    () => () => {
      entryBefore = undefined;
    },
    [],
  );
  useEffect(() => {
    if (current.current.key === location.key) return;
    if (navigationType === "PUSH") before.current = current.current.path;
    else if (navigationType === "POP") before.current = undefined;
    entryBefore = before.current;
    current.current = { key: location.key, path: location.pathname };
  }, [location, navigationType]);

  return () => {
    if (returnTarget) {
      goTo(navigate, location, returnTarget, before.current);
    } else if (!basePath || trimmed(location.pathname) === trimmed(basePath)) {
      navigate(homePath);
    } else if (hasHistoryToPop(location)) {
      navigate(-1);
    } else {
      // Nothing in the history to pop: one screen up, or home when the module
      // has none above this one.
      navigate(
        parentWithinModule(location.pathname, basePath, routeExists) ??
          homePath,
        { replace: true },
      );
    }
  };
}

/**
 * A button that leads back to a named screen the reader came from — "Back to
 * start" on a posted result. It pops when that screen is the entry before,
 * and puts it in place of this one otherwise, so Back from the start never
 * returns to the form that was just finished.
 */
export function useBackToScreen(target: string): () => void {
  const navigate = useNavigate();
  const location = useLocation();
  return () => goTo(navigate, location, target, entryBefore);
}
