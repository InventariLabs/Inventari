import { useEffect, useRef } from "react";
import {
  useLocation,
  useNavigate,
  useNavigationType,
  type Location,
} from "react-router-dom";
import { useReturnTarget } from "@/hooks/useReturnTarget";

const trimmed = (path: string) => path.replace(/\/+$/, "") || "/";

/**
 * The screen one level up inside a module: `/inventory/items/42` ->
 * `/inventory/items`. Never climbs out of the module — its root is the top.
 */
function parentWithinModule(pathname: string, basePath: string): string {
  const base = trimmed(basePath);
  const parent = trimmed(pathname).split("/").slice(0, -1).join("/") || "/";
  return parent.startsWith(base) ? parent : base;
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
 * 4. a screen opened by a direct link has no history to pop, so it climbs to its parent in the module.
 */
export function useShellBack(
  basePath: string | undefined,
  homePath: string,
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
  useEffect(() => {
    if (current.current.key === location.key) return;
    if (navigationType === "PUSH") before.current = current.current.path;
    else if (navigationType === "POP") before.current = undefined;
    current.current = { key: location.key, path: location.pathname };
  }, [location, navigationType]);

  return () => {
    if (returnTarget) {
      const targetPath = trimmed(returnTarget.split(/[?#]/)[0]);
      if (
        before.current !== undefined &&
        trimmed(before.current) === targetPath
      ) {
        navigate(-1);
      } else {
        navigate(returnTarget, { replace: true });
      }
    } else if (!basePath || trimmed(location.pathname) === trimmed(basePath)) {
      navigate(homePath);
    } else if (hasHistoryToPop(location)) {
      navigate(-1);
    } else {
      navigate(parentWithinModule(location.pathname, basePath), {
        replace: true,
      });
    }
  };
}
