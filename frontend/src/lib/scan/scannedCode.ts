/** A label's scan address: the short path labels carry now, the app's own
 *  scan page the first stickers carried, or the `?code=` query before both. */
const SCAN_ADDRESS =
  /^https?:\/\/(?:\[[^\]/]*\]|[^/?#[\]]+)(?:\/(?:s|labels\/scan)\/([^?#]+)|\/[^?#]*\?(?:[^#]*&)?code=([^&#]+))/i;

/**
 * The code a scan names, out of whatever the sticker wrapped it in.
 *
 * A QR carries a scan address, and a 2D hardware scanner types that whole
 * address into the field with the focus; a scan field matches codes. The
 * three shapes a label has printed give back the code; anything else is the
 * code as read. The server reads the same shapes (`app.core.scan_links`).
 */
export function scannedCode(raw: string): string {
  const read = raw.trim();
  const match = SCAN_ADDRESS.exec(read);
  const code = match?.[1] ?? match?.[2];
  if (!code) return read;
  try {
    return decodeURIComponent(code);
  } catch {
    return read;
  }
}
