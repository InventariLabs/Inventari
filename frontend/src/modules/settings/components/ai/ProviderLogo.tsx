import { useState } from "react";
import { Server, Settings } from "lucide-react";

import { getProviderDescriptor } from "@/modules/settings/components/ai/providers";
import type { LlmProvider } from "@/types/ai";

interface ProviderLogoProps {
  provider: LlmProvider;
  size?: number;
  className?: string;
}

/**
 * Renders a provider's brand logo from /public/logos/*.svg with a graceful
 * fallback to a lucide icon (Server for local, Settings for custom) when the
 * logo asset is missing or fails to load at runtime. Keeps the tile grid
 * usable while a brand SVG is being sourced.
 */
export function ProviderLogo({
  provider,
  size = 24,
  className,
}: ProviderLogoProps) {
  const descriptor = getProviderDescriptor(provider);
  const [errored, setErrored] = useState(false);

  if (descriptor?.logo && !errored) {
    // alt="" — decorative. The provider name is rendered as text next to
    // the logo (in the tile), so exposing it twice would duplicate the
    // button's accessible name.
    return (
      <img
        src={descriptor.logo}
        alt=""
        width={size}
        height={size}
        className={className}
        onError={() => setErrored(true)}
      />
    );
  }

  // Fallback icons per group. Custom uses Settings; local/unknown use Server.
  const iconName = descriptor?.icon;
  const Icon = iconName === "Settings" ? Settings : Server;
  // aria-hidden — decorative. The provider name is in the adjacent span;
  // exposing it on the icon would duplicate the button's accessible name.
  return (
    <Icon
      size={size}
      className={className}
      aria-hidden="true"
      focusable={false}
    />
  );
}
