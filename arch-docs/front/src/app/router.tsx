import { Navigate, createBrowserRouter } from "react-router-dom";
import { AppShell } from "./app-shell";
import { DashboardPage } from "../features/dashboard/dashboard-page";
import { SetupPage } from "../features/setup/setup-page";
import { ProjectsPage } from "../features/workflow/projects-page";
import { ProjectPage } from "../features/workflow/project-page";
import { DocsPage } from "../features/docs/docs-page";

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/setup", element: <SetupPage /> },
      { path: "/projects", element: <ProjectsPage /> },
      { path: "/projects/:conversationId", element: <ProjectPage /> },
      { path: "/docs", element: <DocsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
