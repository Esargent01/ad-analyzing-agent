import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-full border border-[var(--border)] bg-white " +
          "px-4 text-sm text-[var(--text)] placeholder:text-[var(--text-tertiary)] " +
          "focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/20 " +
          "focus:border-[var(--border-strong)] disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
