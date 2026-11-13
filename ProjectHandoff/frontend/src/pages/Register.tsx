import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../state/AuthContext";
import { Button, Card, ErrorNote, Field, Input } from "../components/ui";

export function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await register(name, email, password);
      navigate("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
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
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Create your account</h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            You can create a new team afterwards, or use an invite link.
          </p>
        </div>
        <Card className="p-6">
          <form onSubmit={submit} className="space-y-4">
            {error && <ErrorNote message={error} />}
            <Field label="Full name">
              <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Rivera" />
            </Field>
            <Field label="Email">
              <Input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="alex@school.edu"
              />
            </Field>
            <Field label="Password" hint="At least 8 characters.">
              <Input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
              />
            </Field>
            <Button type="submit" loading={loading} className="w-full">
              Create account
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-zinc-500 dark:text-zinc-400">
            Already registered?{" "}
            <Link to="/login" className="font-medium text-indigo-600 hover:underline dark:text-indigo-400">
              Sign in
            </Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
