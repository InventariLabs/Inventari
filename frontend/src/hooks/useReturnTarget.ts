import { useLocation } from "react-router-dom";

/**
 * Where a screen reached from another module's screen sends the back arrow.
 * The linking page passes `state={{ backTo: "/warehouse/todo" }}`; a screen
 * that can be entered that way hands the answer to its header. Only in-app
 * paths count — router state can be written by anything that navigates.
 */
export function useReturnTarget(): string | undefined {
  const state = useLocation().state as { backTo?: unknown } | null;
  const target = state?.backTo;
  return typeof target === "string" &&
    target.startsWith("/") &&
    !target.startsWith("//")
    ? target
    : undefined;
}
