import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { useAuth } from "../state/AuthContext";
import { Button, Card, ErrorNote, Field, Input } from "../components/ui";

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-600 text-lg font-bold text-white">
            PH
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">ProjectHandoff</h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Structured handovers, so nothing is lost when work changes hands.
          </p>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            {error && <ErrorNote message={error} />}
            <Field label="Email">
              <Input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@school.edu"
              />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </Field>
            <Button type="submit" loading={loading} className="w-full">
              Sign in <ArrowRight className="h-4 w-4" aria-hidden />
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-zinc-500 dark:text-zinc-400">
            No account?{" "}
            <Link to="/register" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Create one
            </Link>
            {" · "}
            <Link to="/join" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Join a team
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
