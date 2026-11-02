import React, { useMemo } from "react";
import { moduleRegistry } from "../lib/moduleRegistry";
import { useModules } from "../contexts/ModulesContext";
import type { SlotDataMap } from "../lib/moduleRegistry";
import ErrorBoundary from "./ErrorBoundary";

interface SlotProps {
  name: string;
  data?: unknown;
  className?: string;
  fallback?: React.ReactNode;
}

type SlotComponent = (props: { data: unknown }) => React.ReactNode;

/**
 * Slot component that renders content from multiple modules.
 * Supports priorities and fallback UI.
 *
 * For compile-time type safety use TypedSlot<K> instead.
 */
export const Slot: React.FC<SlotProps> = ({
  name,
  data,
  className,
  fallback,
}) => {
  const { enabledModules } = useModules();

  const components = useMemo(() => {
    return moduleRegistry.getSlotComponents(
      name,
      enabledModules,
    ) as SlotComponent[];
  }, [name, enabledModules]);

  if (components.length === 0) {
    return <>{fallback || null}</>;
  }

  return (
    <div className={`slot-container slot-${name} ${className || ""}`}>
      <React.Suspense fallback={null}>
        {components.map((Component, index) => (
          <ErrorBoundary key={`${name}-${index}`} variant="mini">
            <Component data={data} />
          </ErrorBoundary>
        ))}
      </React.Suspense>
    </div>
  );
};

// ---------------------------------------------------------------------------
// TypedSlot — type-safe variant using SlotDataMap contracts
// ---------------------------------------------------------------------------

interface TypedSlotProps<K extends keyof SlotDataMap> {
  name: K;
  data: SlotDataMap[K];
  className?: string;
  fallback?: React.ReactNode;
}

/**
 * Type-safe version of Slot.
 * The ``data`` prop is validated against ``SlotDataMap[name]`` at compile time.
 *
 * @example
 * <TypedSlot name="item_edit_extra" data={{ item, formData, handleInputChange }} />
 */
export function TypedSlot<K extends keyof SlotDataMap>({
  name,
  data,
  className,
  fallback,
}: TypedSlotProps<K>) {
  return (
    <Slot
      name={name as string}
      data={data}
      className={className}
      fallback={fallback}
    />
  );
}
