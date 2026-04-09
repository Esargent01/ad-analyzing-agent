import type { LabelHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Label({
  className,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "mb-1 block text-[11px] font-medium uppercase tracking-[0.4px] " +
          "text-[var(--text-tertiary)]",
        className,
      )}
      {...props}
    />
  );
}
