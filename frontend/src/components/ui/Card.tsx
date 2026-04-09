import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Card({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--border)] bg-[var(--bg)] p-5",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ children }: { children: ReactNode }) {
  return <div className="mb-3 flex items-center justify-between">{children}</div>;
}

export function CardTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-[15px] font-medium text-[var(--text)]">{children}</h2>
  );
}

export function CardDescription({ children }: { children: ReactNode }) {
  return (
    <p className="mt-1 text-xs text-[var(--text-secondary)]">{children}</p>
  );
}

export function CardContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-sm", className)} {...props} />;
}
