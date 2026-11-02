import { onCLS, onINP, onLCP } from "web-vitals";
import type { Metric } from "web-vitals";

export function initWebVitals() {
  const send = (metric: Metric) => {
    if (import.meta.env.PROD) {
      // eslint-disable-next-line no-console -- performance metrics diagnostics
      console.info(
        `[Web Vitals] ${metric.name}: ${metric.value.toFixed(1)} (id: ${metric.id})`,
      );
      // TODO: send to analytics endpoint
    }
  };

  onCLS(send);
  onINP(send);
  onLCP(send);
}
