import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthedLayout } from "@/routes/_layout";
import { CampaignDetailRoute } from "@/routes/campaign-detail";
import { DashboardRoute } from "@/routes/dashboard";
import { MagicLinkSentRoute } from "@/routes/magic-link-sent";
import { SignInRoute } from "@/routes/sign-in";

/**
 * Explicit route table — no file-based routing, no loaders. TanStack
 * Query hooks fetch inside each route component.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <Navigate to="/dashboard" replace />,
  },
  {
    path: "/sign-in",
    element: <SignInRoute />,
  },
  {
    path: "/magic-link-sent",
    element: <MagicLinkSentRoute />,
  },
  {
    element: <AuthedLayout />,
    children: [
      {
        path: "/dashboard",
        element: <DashboardRoute />,
      },
      {
        path: "/campaigns/:campaignId",
        element: <CampaignDetailRoute />,
      },
    ],
  },
  {
    path: "*",
    element: <Navigate to="/dashboard" replace />,
  },
]);
