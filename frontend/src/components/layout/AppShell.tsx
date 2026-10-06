import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { getHealth } from "../../api/strata";

type ConnectionState = "checking" | "connected" | "unavailable";

const navigation = [
  ["/", "Overview"],
  ["/tasks", "Tasks"],
  ["/board", "Board"],
  ["/sql", "SQL Console"],
  ["/engine", "Engine"],
] as const;

export function AppShell() {
  const [connection, setConnection] = useState<ConnectionState>("checking");

  useEffect(() => {
    let active = true;
    void getHealth().then(
      () => active && setConnection("connected"),
      () => active && setConnection("unavailable"),
    );
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <a className="font-semibold tracking-tight" href="/">Strata</a>
          <span aria-live="polite" className="text-sm text-slate-600">
            Backend: {connection}
          </span>
        </div>
      </header>
      <div className="mx-auto grid max-w-5xl gap-6 px-6 py-6 md:grid-cols-[10rem_1fr]">
        <nav aria-label="Primary navigation" className="flex gap-3 md:flex-col">
          {navigation.map(([to, label]) => (
            <NavLink
              className={({ isActive }) =>
                `text-sm ${isActive ? "font-semibold text-slate-950" : "text-slate-600"}`
              }
              end={to === "/"}
              key={to}
              to={to}
            >
              {label}
            </NavLink>
          ))}
        </nav>
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
