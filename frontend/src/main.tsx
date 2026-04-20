import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { initAnalytics } from "@/lib/analytics";
import "@/styles/globals.css";

// Fire PostHog init before React mounts so the initial $pageview is
// captured. Subsequent React Router navigations auto-fire via the
// ``capture_pageview: 'history_change'`` config — no per-route hook
// needed. See ``src/lib/analytics.ts`` for the full rationale.
initAnalytics();

const container = document.getElementById("root");
if (!container) {
  throw new Error("Root container #root not found in index.html");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
