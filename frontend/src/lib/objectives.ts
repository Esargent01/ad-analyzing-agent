/**
 * Client-side objective helpers.
 *
 * The Python profile module at ``src/services/objectives.py`` is the
 * source of truth for how each Meta campaign objective renders —
 * headline cards, summary numbers, diagnostic tiles, variant-table
 * columns are all pre-computed server-side and shipped on the
 * ``DailyReport`` / ``WeeklyReport`` response. That means most
 * objective-awareness on the React side is "iterate the list" rather
 * than branching on the objective string directly.
 *
 * This module covers the few places where the frontend still has to
 * pick a label or a chip copy per objective (mostly the import picker
 * and the eyebrow above the top-line metric grid).
 */

const DISPLAY_LABELS: Record<string, string> = {
  OUTCOME_SALES: "Sales",
  OUTCOME_LEADS: "Leads",
  OUTCOME_ENGAGEMENT: "Engagement",
  OUTCOME_TRAFFIC: "Traffic",
  OUTCOME_AWARENESS: "Awareness",
  OUTCOME_APP_PROMOTION: "App promotion",
  OUTCOME_UNKNOWN: "Unknown",
};

/** Short, human-readable label for an ODAX objective. Falls back to
 *  "Unknown" for values we haven't mapped (including deferred
 *  ``OUTCOME_APP_PROMOTION`` → should render via its own label, but
 *  downstream render paths treat it as Sales). */
export function objectiveLabel(objective: string | null | undefined): string {
  if (!objective) return "Unknown";
  return DISPLAY_LABELS[objective] ?? "Unknown";
}

/** Eyebrow text for the daily top-line metric grid. Reads nicely
 *  under the page title across every objective. */
export function topLineLabelFor(objective: string): string {
  switch (objective) {
    case "OUTCOME_SALES":
      return "Top-line \u00B7 today";
    case "OUTCOME_LEADS":
      return "Leads \u00B7 today";
    case "OUTCOME_ENGAGEMENT":
      return "Engagement \u00B7 today";
    case "OUTCOME_TRAFFIC":
      return "Traffic \u00B7 today";
    case "OUTCOME_AWARENESS":
      return "Awareness \u00B7 today";
    default:
      return "Top-line \u00B7 today";
  }
}

/** True when the objective is one we render fully; false for deferred
 *  (App Promotion) or unknown values which fall back to Sales output. */
export function isFullySupported(objective: string | null | undefined): boolean {
  if (!objective) return false;
  return (
    objective === "OUTCOME_SALES" ||
    objective === "OUTCOME_LEADS" ||
    objective === "OUTCOME_ENGAGEMENT" ||
    objective === "OUTCOME_TRAFFIC" ||
    objective === "OUTCOME_AWARENESS"
  );
}
