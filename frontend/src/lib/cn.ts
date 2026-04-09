/**
 * Tiny className joiner. Filters out falsy values so conditional classes
 * can be expressed as `cn("base", isActive && "active")`.
 *
 * We deliberately skip `clsx` / `tailwind-merge` in Phase 3 — the
 * primitives are small enough that we don't need merge semantics yet.
 */
export function cn(...inputs: Array<string | false | null | undefined>): string {
  return inputs.filter(Boolean).join(" ");
}
