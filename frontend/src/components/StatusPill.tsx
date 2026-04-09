import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type StatusKind =
  | "winner"
  | "steady"
  | "new"
  | "fatigue"
  | "paused"
  | "active"
  | "expiring";

const kindToClass: Record<StatusKind, string> = {
  // Direct matches for the base.html palette
  winner: "status-pill status-winner",
  steady: "status-pill status-steady",
  new: "status-pill status-new",
  fatigue: "status-pill status-fatigue",
  paused: "status-pill status-paused",
  // Aliases — "active" reads as winner-green, "expiring" as amber fatigue
  active: "status-pill status-winner",
  expiring: "status-pill status-fatigue",
};

export interface StatusPillProps {
  kind: StatusKind;
  children: ReactNode;
  className?: string;
}

/**
 * Status badge matching the `.status-*` pill styles from the base Jinja
 * template. Single component covers every variant so callers use the
 * same vocabulary across the app.
 */
export function StatusPill({ kind, children, className }: StatusPillProps) {
  return <span className={cn(kindToClass[kind], className)}>{children}</span>;
}
