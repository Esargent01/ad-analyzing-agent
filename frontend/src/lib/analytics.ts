/**
 * PostHog wiring for the Kleiber marketing + dashboard frontend.
 *
 * Project: "Kleiber" · id 279097 · US cloud.
 * API token is a PostHog ``phc_`` public project key — safe to embed
 * in client-side code. PostHog's own docs explicitly recommend
 * shipping these keys in the browser bundle.
 *
 * What we capture:
 *
 * - **Automatic pageviews** on every React Router navigation. Enabled
 *   via ``capture_pageview: 'history_change'`` which watches the
 *   browser's ``pushState``/``popState`` so SPA route changes fire a
 *   fresh ``$pageview`` event. The event carries ``$pathname`` so we
 *   can split ``/`` vs ``/beta`` in the dashboard.
 *
 * - **Custom funnel events** from the two landing pages' signup forms.
 *   Each event carries a ``landing_variant`` property so funnel
 *   analysis can compare the two without parsing paths:
 *     - ``beta_signup_submit_attempt`` — user clicked submit
 *     - ``beta_signup_success``        — API returned 201
 *     - ``beta_signup_error``          — network error or non-2xx
 *
 * Call ``initAnalytics()`` exactly once at app boot, then use
 * ``trackEvent()`` anywhere.
 */

import posthog from "posthog-js";

// Public project API key. Not a secret — PostHog phc_* keys are
// deliberately client-safe. Hardcoded (rather than a Vite env var) to
// avoid an extra Fly build-env step; if we ever want per-environment
// projects this is the lever to flip.
const POSTHOG_KEY = "phc_Yu18yuld9BNTq8LUBcR0Ujp7LBsPXw9r4gnBV5iGnaB";
const POSTHOG_HOST = "https://us.i.posthog.com";

/**
 * Landing-page variant tag. The A/B test lives between the original
 * ``/`` and the ``/beta`` variant. Every signup-funnel event carries
 * one of these values so PostHog's funnel view can split by variant.
 */
export type LandingVariant = "original" | "scientific";

/**
 * Names of the custom events we fire. Enumerated here so a typo in a
 * call site fails at the TypeScript layer instead of silently
 * polluting the PostHog event stream.
 */
export type AnalyticsEvent =
  | "beta_signup_submit_attempt"
  | "beta_signup_success"
  | "beta_signup_error";

/**
 * Initialize PostHog. Safe to call in any environment — if the script
 * fails to load (ad blocker, offline, etc.) posthog-js silently
 * degrades and ``capture()`` becomes a no-op.
 *
 * Call once, at app boot, before React renders.
 */
export function initAnalytics(): void {
  // Guard against double-init in React 18 strict-mode dev double-mount.
  if (typeof window === "undefined") return;
  if ((window as { __POSTHOG_INITIALIZED__?: boolean }).__POSTHOG_INITIALIZED__) {
    return;
  }

  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    // SPA-friendly: fire $pageview on every pushState/popState, not
    // just on the hard page load. Without this, React Router
    // navigations (e.g. / → /beta) never produce a pageview event.
    capture_pageview: "history_change",
    // We want ``$current_url`` and ``$pathname`` on every event for
    // splitting by route — posthog-js captures these by default with
    // no extra config, but flipping ``person_profiles`` to
    // ``identified_only`` would cut per-anon-session properties.
    // Default behavior is fine for our purposes.
    autocapture: true,
    // Skip PostHog's feature-flag bootstrap — we don't use flags yet
    // and the extra request on every page load is pure overhead.
    disable_session_recording: true,
  });

  (window as { __POSTHOG_INITIALIZED__?: boolean }).__POSTHOG_INITIALIZED__ = true;
}

/**
 * Fire a named event with optional properties. Centralizes the cast
 * around ``posthog.capture`` so every call site goes through a typed
 * wrapper (prevents free-form event name strings from creeping in).
 *
 * Properties are a loose ``Record<string, unknown>`` on purpose —
 * PostHog treats them as JSON and we want call-site flexibility
 * without a brittle per-event schema.
 */
export function trackEvent(
  event: AnalyticsEvent,
  properties?: Record<string, unknown>,
): void {
  try {
    posthog.capture(event, properties);
  } catch {
    // Analytics must never take down the user flow. Swallow any
    // posthog-side error (uninitialized, network, script blocked)
    // and continue.
  }
}

/**
 * Convenience: fire a signup-funnel event with the ``landing_variant``
 * tag already attached. Thin sugar over ``trackEvent`` used by both
 * landing-page components so we can't accidentally forget the tag.
 */
export function trackSignupEvent(
  event: AnalyticsEvent,
  variant: LandingVariant,
  extra?: Record<string, unknown>,
): void {
  trackEvent(event, { landing_variant: variant, ...(extra ?? {}) });
}
