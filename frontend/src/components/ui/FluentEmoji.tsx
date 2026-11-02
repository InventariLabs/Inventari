import { useState } from "react";
import { FluentEmojiManifest } from "@/lib/fluent-emoji-manifest";

export interface FluentEmojiProps {
  /** A single emoji grapheme, e.g. "🥚". */
  emoji: string;
  /** Pixel size. Default 24. */
  size?: number;
  className?: string;
  /** Override the alt text (default = the emoji). */
  alt?: string;
}

/**
 * Renders a self-hosted Fluent UI Emoji SVG.
 *
 * Self-hosting guarantees pixel-identical rendering on every OS.
 *
 * Falls back to the native font emoji when:
 *  - the emoji is not in ``FluentEmojiManifest`` (e.g. user-picked emoji
 *    outside our curated subset), or
 *  - the SVG ``<img>`` fails to load (network error, file removed).
 *
 * Both fallback paths render the glyph as a ``<span>`` with a reasonable
 * font size so the layout stays consistent.
 */
export function FluentEmoji({
  emoji,
  size = 24,
  className,
  alt,
}: FluentEmojiProps) {
  const [failed, setFailed] = useState(false);
  const svgPath = FluentEmojiManifest[emoji];

  if (!svgPath || failed) {
    return (
      <span
        role="img"
        aria-label={alt ?? emoji}
        className={className}
        style={{
          fontSize: Math.round(size * 0.8),
          lineHeight: 1,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: size,
          height: size,
        }}
      >
        {emoji}
      </span>
    );
  }

  return (
    <img
      src={svgPath}
      width={size}
      height={size}
      alt={alt ?? emoji}
      className={className}
      loading="lazy"
      decoding="async"
      style={{ display: "inline-block", objectFit: "contain" }}
      onError={() => setFailed(true)}
    />
  );
}
