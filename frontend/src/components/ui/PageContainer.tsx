import { cn } from "@/lib/utils";

interface PageContainerProps {
  children: React.ReactNode;
  wide?: boolean;
  className?: string;
}

export function PageContainer({
  children,
  wide,
  className,
}: PageContainerProps) {
  return (
    <div
      className={cn(
        "mx-auto w-full pb-32",
        wide ? "max-w-[1920px]" : "max-w-screen-2xl",
        className,
      )}
    >
      {children}
    </div>
  );
}
