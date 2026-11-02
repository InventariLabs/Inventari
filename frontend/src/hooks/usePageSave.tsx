import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

/** One piece of a settings page that can hold unsaved work. */
interface PageSavePart {
  dirty: boolean;
  /** Writes this part; a rejection is reported by the caller of `saveAll`. */
  save: () => Promise<unknown>;
}

interface PageSaveContextValue {
  dirty: boolean;
  saving: boolean;
  /** Saves every dirty part, one after another; resolves with the failures. */
  saveAll: () => Promise<unknown[]>;
  register: (key: string, part: PageSavePart) => void;
  unregister: (key: string) => void;
}

const PageSaveContext = createContext<PageSaveContextValue | null>(null);

/**
 * The one Save of a settings page (UI_GUIDELINES §11.9).
 *
 * A page made of several sections, each with its own request, used to carry
 * one Save button per fragment, and a reader could not tell which edits
 * a given button would keep. Here every section registers itself as a part
 * while it holds an edit; the page shows a single Save when any part is dirty
 * and writes them in turn.
 */
export function PageSaveProvider({ children }: { children: ReactNode }) {
  const parts = useRef(new Map<string, PageSavePart>());
  const [dirtyKeys, setDirtyKeys] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const register = useCallback((key: string, part: PageSavePart) => {
    parts.current.set(key, part);
    setDirtyKeys((current) => {
      if (current.has(key) === part.dirty) return current;
      const next = new Set(current);
      if (part.dirty) next.add(key);
      else next.delete(key);
      return next;
    });
  }, []);

  const unregister = useCallback((key: string) => {
    parts.current.delete(key);
    setDirtyKeys((current) => {
      if (!current.has(key)) return current;
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  }, []);

  const saveAll = useCallback(async () => {
    setSaving(true);
    const failures: unknown[] = [];
    try {
      for (const part of [...parts.current.values()]) {
        if (!part.dirty) continue;
        try {
          await part.save();
        } catch (error) {
          failures.push(error);
        }
      }
    } finally {
      setSaving(false);
    }
    return failures;
  }, []);

  const value = useMemo(
    () => ({
      dirty: dirtyKeys.size > 0,
      saving,
      saveAll,
      register,
      unregister,
    }),
    [dirtyKeys, saving, saveAll, register, unregister],
  );

  return (
    <PageSaveContext.Provider value={value}>
      {children}
    </PageSaveContext.Provider>
  );
}

/** The page's own view of the save: is anything dirty, and write it. */
export function usePageSave() {
  const ctx = useContext(PageSaveContext);
  if (!ctx) throw new Error("usePageSave needs a PageSaveProvider");
  return ctx;
}

/**
 * Registers a section's edit with the page's Save. Outside a provider it does
 * nothing and returns `false`, so a form that is also used on its own can keep
 * its own button when this answers `false`.
 */
export function usePageSavePart(
  key: string,
  dirty: boolean,
  save: () => Promise<unknown>,
): boolean {
  const ctx = useContext(PageSaveContext);
  const saveRef = useRef(save);
  saveRef.current = save;
  const register = ctx?.register;
  const unregister = ctx?.unregister;
  useEffect(() => {
    register?.(key, { dirty, save: () => saveRef.current() });
  }, [register, key, dirty]);
  useEffect(() => () => unregister?.(key), [unregister, key]);
  return ctx !== null;
}

/** Whether the caller sits under a page Save, and so should not show its own. */
export function useUnderPageSave(): boolean {
  return useContext(PageSaveContext) !== null;
}
