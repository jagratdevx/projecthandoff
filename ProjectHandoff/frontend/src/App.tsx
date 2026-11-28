import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./state/AuthContext";
import { Layout } from "./components/Layout";
import { RouteErrorBoundary } from "./components/RouteErrorBoundary";
import { Spinner } from "./components/ui";
import { Dashboard } from "./pages/Dashboard";
import { Projects } from "./pages/Projects";
import { ProjectDetail } from "./pages/ProjectDetail";
import { Tasks } from "./pages/Tasks";
import { TaskDetail } from "./pages/TaskDetail";
import { Handovers } from "./pages/Handovers";
import { HandoverDetail } from "./pages/HandoverDetail";
import { Events } from "./pages/Events";
import { EventDetail } from "./pages/EventDetail";
import { TeamPage } from "./pages/Team";
import { SubteamProjects } from "./pages/SubteamProjects";
import { Memories } from "./pages/Memories";
import { ActivityPage } from "./pages/Activity";
import { Settings } from "./pages/Settings";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
import { JoinTeam } from "./pages/JoinTeam";
import { Setup } from "./pages/Setup";

/** Scroll to top on route change. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

/** Redirects signed-in users away from auth screens; renders a splash while the session is checked. */
function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (user) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

/**
 * Protected layout route: guards every child route and mounts the app chrome.
 * Layout renders <Outlet />, so this is used as a pathless parent route element.
 */
function ProtectedLayout() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Layout />;
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/login" element={<AuthGate><Login /></AuthGate>} />
        <Route path="/register" element={<AuthGate><Register /></AuthGate>} />
        <Route path="/join" element={<AuthGate><JoinTeam /></AuthGate>} />
        <Route path="/setup" element={<Setup />} />

        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:id" element={<ProjectDetail />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/tasks/:id" element={<TaskDetail />} />
          <Route path="/handovers" element={<Handovers />} />
          <Route path="/handovers/:id" element={<HandoverDetail />} />
          <Route path="/events" element={<Events />} />
          <Route path="/events/:id" element={<EventDetail />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/team/subteams/:subteamId/projects" element={<SubteamProjects />} />
          <Route path="/memories" element={<RouteErrorBoundary label="Memories"><Memories /></RouteErrorBoundary>} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/settings" element={<Settings />} />
        </Route>

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </>
  );
}
