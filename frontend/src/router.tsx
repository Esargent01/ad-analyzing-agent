import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthedLayout } from "@/routes/_layout";
import { CampaignDetailRoute } from "@/routes/campaign-detail";
import { DailyReportDetailRoute } from "@/routes/daily-report-detail";
import { DashboardRoute } from "@/routes/dashboard";
import { MagicLinkSentRoute } from "@/routes/magic-link-sent";
import { ReportsDailyListRoute } from "@/routes/reports-daily-list";
import { ReportsWeeklyListRoute } from "@/routes/reports-weekly-list";
import { SignInRoute } from "@/routes/sign-in";
import { WeeklyReportDetailRoute } from "@/routes/weekly-report-detail";

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
      {
        path: "/campaigns/:campaignId/reports/daily",
        element: <ReportsDailyListRoute />,
      },
      {
        path: "/campaigns/:campaignId/reports/daily/:reportDate",
        element: <DailyReportDetailRoute />,
      },
      {
        path: "/campaigns/:campaignId/reports/weekly",
        element: <ReportsWeeklyListRoute />,
      },
      {
        path: "/campaigns/:campaignId/reports/weekly/:weekStart",
        element: <WeeklyReportDetailRoute />,
      },
    ],
  },
  {
    path: "*",
    element: <Navigate to="/dashboard" replace />,
  },
]);
