const KEY = "inventari-language-choice";

/**
 * Remembers a language the user picked while signed out.
 *
 * The sign-in screen offers a language selector, but with no session there is
 * nowhere to save the choice: signing in then applied the account's
 * `preferred_language` — "en" for a fresh account — and the choice was gone.
 * This is deliberately separate from i18next's own `i18nextLng` cache, which
 * also holds languages merely *detected* from the browser; only an explicit
 * pick belongs here.
 */
export function rememberLanguageChoice(language: string): void {
  try {
    localStorage.setItem(KEY, language);
  } catch {
    // Private mode or a full quota — the choice simply does not survive.
  }
}

/** Reads and clears the pending choice, if any. */
export function takeLanguageChoice(): string | null {
  try {
    const value = localStorage.getItem(KEY);
    if (value) localStorage.removeItem(KEY);
    return value;
  } catch {
    return null;
  }
}
