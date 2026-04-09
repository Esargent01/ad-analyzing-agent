import { createBrowserRouter, Navigate } from "react-router-dom";

import { AuthedLayout } from "@/routes/_layout";
import { CampaignDetailRoute } from "@/routes/campaign-detail";
import { DashboardRoute } from "@/routes/dashboard";
import { MagicLinkSentRoute } from "@/routes/magic-link-sent";
import {
  DailyReportDetailStub,
  WeeklyReportDetailStub,
} from "@/routes/report-detail-stub";
import { ReportsDailyListRoute } from "@/routes/reports-daily-list";
import { ReportsWeeklyListRoute } from "@/routes/reports-weekly-list";
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
      {
        path: "/campaigns/:campaignId/reports/daily",
        element: <ReportsDailyListRoute />,
      },
      {
        path: "/campaigns/:campaignId/reports/daily/:reportDate",
        element: <DailyReportDetailStub />,
      },
      {
        path: "/campaigns/:campaignId/reports/weekly",
        element: <ReportsWeeklyListRoute />,
      },
      {
        path: "/campaigns/:campaignId/reports/weekly/:weekStart",
        element: <WeeklyReportDetailStub />,
      },
    ],
  },
  {
    path: "*",
    element: <Navigate to="/dashboard" replace />,
  },
]);
