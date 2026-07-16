import { Navigate, createBrowserRouter } from "react-router-dom";
import { AppShell } from "./app-shell";
import { DashboardPage } from "../features/dashboard/dashboard-page";
import { SetupPage } from "../features/setup/setup-page";
import { InitWorkflowStartPage } from "../features/workflow/init-workflow-start-page";
import { InitWorkflowPage } from "../features/workflow/init-workflow-page";
import { DocsPage } from "../features/docs/docs-page";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/setup", element: <SetupPage /> },
      { path: "/workflows/init", element: <InitWorkflowStartPage /> },
      { path: "/workflows/init/:conversationId", element: <InitWorkflowPage /> },
      { path: "/docs", element: <DocsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
