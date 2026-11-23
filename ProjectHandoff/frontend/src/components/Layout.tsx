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
      <div className="flex items-center gap-3 px-5 pb-5 pt-6">
        <img src="/logo.png" alt="ProjectHandoff logo" className="h-9 w-9 rounded-xl shadow-sm ring-1 ring-inset ring-black/5" />
        <div className="min-w-0">
          <p className="truncate text-[15px] font-semibold tracking-tight text-stone-900 dark:text-stone-50">ProjectHandoff</p>
          <p className="truncate text-[11px] leading-tight text-stone-500 dark:text-stone-400">{team?.name ?? "No team yet"}</p>
        </div>
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-3" aria-label="Main navigation">
        <p className="eyebrow px-3 pb-2">Workspace</p>
        <div className="space-y-0.5">
          {NAV_ITEMS.map(({ to, label, icon: Icon, badge }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${
                  isActive
                    ? "bg-stone-900 text-white shadow-sm dark:bg-stone-100 dark:text-stone-900"
                    : "text-stone-600 hover:bg-stone-200/50 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
                }`
              }
            >
              <Icon className="h-[18px] w-[18px]" aria-hidden />
              <span className="flex-1">{label}</span>
              {badge && handoverCount > 0 && (
                <span className="rounded-full bg-brand-600 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-white">
                  {handoverCount}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
      <div className="border-t border-stone-200/80 p-3 dark:border-stone-800/80">
        <div className="flex items-center gap-2.5 rounded-xl px-2 py-2">
          <Avatar name={user?.name ?? ""} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-stone-900 dark:text-stone-100">{user?.name}</p>
            <p className="truncate text-xs text-stone-500 dark:text-stone-400">{user?.email}</p>
          </div>
          {user && <Badge value={user.role} />}
        </div>
        <button
          onClick={handleLogout}
          className="mt-1 flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium text-stone-600 transition hover:bg-stone-200/50 hover:text-stone-900 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100"
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
      <aside className="hidden w-60 shrink-0 border-r border-stone-200/80 bg-[#efede8]/70 dark:border-stone-800/80 dark:bg-stone-900/60 lg:block">
        <div className="sticky top-0 h-screen">{sidebar}</div>
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div id="mobile-nav" className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-stone-950/40 backdrop-blur-sm" onClick={() => setSidebarOpen(false)} aria-hidden />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="absolute left-0 top-0 h-full w-60 max-w-[85vw] border-r border-stone-200/80 bg-[#fbfaf8] shadow-card-hover dark:border-stone-800/80 dark:bg-stone-900"
          >
            <button
              onClick={() => setSidebarOpen(false)}
              className="absolute right-2 top-2 rounded-lg p-2 text-stone-500 hover:bg-stone-200/60 dark:hover:bg-stone-800"
              aria-label="Close navigation"
            >
              <X className="h-4 w-4" aria-hidden />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-stone-200/80 bg-[#f6f5f2]/80 px-4 backdrop-blur-md dark:border-stone-800/80 dark:bg-stone-950/80 sm:px-6 lg:px-10">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-lg p-2 text-stone-500 hover:bg-stone-200/60 dark:hover:bg-stone-800 lg:hidden"
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
            className="rounded-lg p-2 text-stone-500 transition hover:bg-stone-200/60 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-100"
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            aria-label="Toggle color theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
          </button>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 lg:px-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
