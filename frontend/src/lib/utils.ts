import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Return the URL only when it is a web link, otherwise null.
 *
 * React does not block `javascript:` in `href`, so any stored URL rendered
 * into a link needs this gate — clicking such a link runs the payload in the
 * victim's session. Callers render the plain text when this returns null.
 */
export function webLinkOrNull(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
