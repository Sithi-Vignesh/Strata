import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { ProductProvider } from "./ProductContext";
import { BoardPage } from "../pages/BoardPage";
import { EnginePage } from "../pages/EnginePage";
import { OverviewPage } from "../pages/OverviewPage";
import { SqlConsolePage } from "../pages/SqlConsolePage";
import { TasksPage } from "../pages/TasksPage";

export const routes = [
  {
    element: <ProductProvider><AppShell /></ProductProvider>,
    children: [
      { path: "/", element: <OverviewPage /> },
      { path: "/tasks", element: <TasksPage /> },
      { path: "/board", element: <BoardPage /> },
      { path: "/sql", element: <SqlConsolePage /> },
      { path: "/engine", element: <EnginePage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
