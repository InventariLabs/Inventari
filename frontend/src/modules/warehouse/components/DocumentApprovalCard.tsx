import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Card } from "@/components/ui/Card";

/**
 * The frame around the approvals slot.
 *
 * The approvals module decides what the slot says, and for a confirmed
 * document with no request and no workflow behind it that is nothing at all.
 * The page cannot know that without reaching into the module, so the frame
 * watches its own content and steps aside while there is none. It uses the
 * `hidden` attribute rather than a class: the stack spacing of the page skips
 * hidden children, so the gap closes with the card.
 */
export function DocumentApprovalCard({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [blank, setBlank] = useState(false);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setBlank((el.textContent ?? "").trim() === "");
    measure();
    const observer = new MutationObserver(measure);
    observer.observe(el, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => observer.disconnect();
  }, []);

  return (
    <Card ref={ref} hidden={blank} className="p-4 sm:p-5">
      {children}
    </Card>
  );
}
