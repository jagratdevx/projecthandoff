import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowLeftRight,
  CalendarDays,
  FolderKanban,
  History,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Moon,
  Settings as SettingsIcon,
  Sun,
  Users,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { Handover } from "../api/types";
import { useAuth } from "../state/AuthContext";
import { useTheme } from "../hooks/useTheme";
import { Avatar, Badge } from "./ui";
import { SyncIndicator } from "./SyncIndicator";

const NAV_ITEMS = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/handovers", label: "Handovers", icon: ArrowLeftRight, badge: true },
  { to: "/events", label: "Events", icon: CalendarDays },
  { to: "/team", label: "Team", icon: Users },
  { to: "/activity", label: "Activity", icon: History },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Layout() {
  const { user, team, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [handoverCount, setHandoverCount] = useState(0);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      if (!team) return;
      try {
        const items = await api<Handover[]>("/api/handovers?direction=incoming&status=pending");
        if (!cancelled) setHandoverCount(items.length);
      } catch {
        /* offline; badge refreshes on next poll */
      }
    };
    void check();
    const interval = window.setInterval(check, 30000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [team]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <img src="/logo.png" alt="ProjectHandoff logo" className="h-8 w-8 rounded-lg" />
        <div>
          <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">ProjectHandoff</p>
          <p className="text-[11px] leading-tight text-zinc-500">{team?.name ?? "No team yet"}</p>
        </div>
      </div>
      <nav className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3" aria-label="Main navigation">
        {NAV_ITEMS.map(({ to, label, icon: Icon, badge }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
                isActive
                  ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              }`
            }
          >
            <Icon className="h-4.5 w-4.5 h-[18px] w-[18px]" aria-hidden />
            <span className="flex-1">{label}</span>
            {badge && handoverCount > 0 && (
              <span className="rounded-full bg-indigo-600 px-1.5 py-0.5 text-[11px] font-semibold text-white">
                {handoverCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-zinc-200 p-3 dark:border-zinc-800">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
          <Avatar name={user?.name ?? ""} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-zinc-900 dark:text-zinc-100">{user?.name}</p>
            <p className="truncate text-xs text-zinc-500">{user?.email}</p>
          </div>
          {user && <Badge value={user.role} />}
        </div>
        <button
          onClick={handleLogout}
          className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 transition hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
        >
          <LogOut className="h-4 w-4" aria-hidden />
          Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="hidden w-60 shrink-0 border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900 lg:block">
        <div className="sticky top-0 h-screen">{sidebar}</div>
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div id="mobile-nav" className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-zinc-950/50" onClick={() => setSidebarOpen(false)} aria-hidden />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute left-0 top-0 h-full w-60 max-w-[85vw] border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
          >
            <button
              onClick={() => setSidebarOpen(false)}
              className="absolute right-2 top-2 rounded-md p-2 text-zinc-500"
              aria-label="Close navigation"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-zinc-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90 sm:px-6">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-2 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 lg:hidden"
            aria-label="Open navigation"
            aria-expanded={sidebarOpen}
            aria-controls="mobile-nav"
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>
          <div className="flex-1" />
          <SyncIndicator />
          <button
            onClick={toggle}
            className="rounded-md p-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            aria-label="Toggle color theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
          </button>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
