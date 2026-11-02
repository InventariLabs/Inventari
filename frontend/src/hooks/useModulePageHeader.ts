import { createContext, useContext, useEffect, type ReactNode } from "react";

interface PageHeaderData {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  /** When set, the shell renders a back arrow button linking to this path. */
  backTo?: string;
  /** Optional badge rendered next to the title (e.g. status). */
  statusBadge?: ReactNode;
}

export type { PageHeaderData };

/**
 * The default `setHeader` used to be `() => {}`, and silence is the wrong
 * answer: only `SettingsShell` and `ModuleShell` provide this context, so a
 * page rendered on a flat route under `AppShell` handed its title and its
 * actions to nothing. `/webhooks` shipped that way — the "Add webhook" button
 * lived in the header it never reached, and once the first webhook existed the
 * empty state (which held the only other copy of that button) disappeared with
 * it, leaving no way to add a second one.
 */
function warnAboutMissingProvider(data: PageHeaderData): void {
  // The hook's own unmount cleanup passes `{}`; that one is not a complaint.
  if (!import.meta.env.DEV || Object.keys(data).length === 0) return;
  // `console.error`, not `warn`: this is a wiring mistake, and the repo
  // allows no other console method.
  console.error(
    "useModulePageHeader: setHeader called outside a PageHeaderContext " +
      `provider — the header (${data.title ?? "untitled"}) and its actions ` +
      "are dropped. Render this page under SettingsShell or ModuleShell.",
  );
}

export const PageHeaderContext = createContext<{
  data: PageHeaderData;
  setHeader: (data: PageHeaderData) => void;
}>({ data: {}, setHeader: warnAboutMissingProvider });

/**
 * Hook for module pages to access the shell-level page header.
 *
 * Auto-cleanup: registers an internal effect that resets the header to
 * empty when the consuming component unmounts. Callers that already do
 * `return () => setHeader({})` inside their own effect can safely remove
 * that manual cleanup line — the hook now handles it automatically.
 */
export function useModulePageHeader() {
  const ctx = useContext(PageHeaderContext);
  const { setHeader } = ctx;

  useEffect(() => {
    return () => {
      setHeader({});
    };
  }, [setHeader]);

  return ctx;
}
