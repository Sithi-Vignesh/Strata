import { createBrowserRouter, Navigate, Outlet } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { BoardPage } from "../pages/BoardPage";
import { EnginePage } from "../pages/EnginePage";
import { OverviewPage } from "../pages/OverviewPage";
import { SqlConsolePage } from "../pages/SqlConsolePage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { TasksPage } from "../pages/TasksPage";
import { AuthPage } from "../pages/AuthPage";
import { MembersPage } from "../pages/MembersPage";
import { MyTasksPage } from "../pages/MyTasksPage";
import { SettingsPage } from "../pages/SettingsPage";
import { InboxPage } from "../pages/InboxPage";
import { AllTasksPage } from "../pages/AllTasksPage";
import { CommonDashboardPage } from "../pages/CommonDashboardPage";
import { AuthProvider, useAuth } from "./AuthContext";
import { ProductProvider } from "./ProductContext";
import { ThemeProvider } from "./ThemeContext";

function ProductRoute() { const auth = useAuth(); if (auth.status === "loading") return <AuthLoading />; if (auth.status === "error") return <AuthFailure />; if (auth.user === null) return <Navigate replace to="/login" />; return <ProductProvider key={auth.user.id} user={auth.user}><AppShell /></ProductProvider>; }
function AuthRoute({ mode }: { mode: "login" | "register" }) { const auth = useAuth(); if (auth.status === "loading") return <AuthLoading />; if (auth.user !== null) return <Navigate replace to="/" />; return <AuthPage mode={mode} />; }
function AuthLoading() { return <main className="flex min-h-svh items-center justify-center text-sm text-[var(--strata-muted)]">Restoring your Strata session…</main>; }
function AuthFailure() { const auth = useAuth(); return <main className="flex min-h-svh items-center justify-center px-5"><div className="rounded-md border border-rose-200 bg-rose-50 p-5 text-sm text-rose-950" role="alert">Could not restore your session. <button className="font-semibold underline" onClick={auth.retry} type="button">Retry</button></div></main>; }

export const routes = [{ element: <ThemeProvider><AuthProvider><Outlet /></AuthProvider></ThemeProvider>, children: [
  { path: "/login", element: <AuthRoute mode="login" /> }, { path: "/register", element: <AuthRoute mode="register" /> },
  { element: <ProductRoute />, children: [{ path: "/", element: <CommonDashboardPage /> }, { path: "/workspace", element: <OverviewPage /> }, { path: "/all-tasks", element: <AllTasksPage /> }, { path: "/my-tasks", element: <MyTasksPage /> }, { path: "/inbox", element: <InboxPage /> }, { path: "/tasks", element: <TasksPage /> }, { path: "/projects", element: <ProjectsPage /> }, { path: "/board", element: <BoardPage /> }, { path: "/members", element: <MembersPage /> }, { path: "/settings", element: <SettingsPage /> }] },
  { element: <AppShell />, children: [{ path: "/sql", element: <SqlConsolePage /> }, { path: "/engine", element: <EnginePage /> }] },
] }];
export const router = createBrowserRouter(routes);
