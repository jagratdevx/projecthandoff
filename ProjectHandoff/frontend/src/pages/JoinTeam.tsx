import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../state/AuthContext";
import { Button, Card, ErrorNote, Field, Input } from "../components/ui";

interface ValidateResponse {
  team_name: string;
  team_id: string;
  role: string;
  email: string;
}

export function JoinTeam() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { register } = useAuth();
  const navigate = useNavigate();

  const [validation, setValidation] = useState<ValidateResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validating, setValidating] = useState(!!token);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [checked, setChecked] = useState(false);

  if (token && !checked) {
    setChecked(true);
    api<ValidateResponse>(`/api/invitations/validate?token=${encodeURIComponent(token)}`, { skipAuth: true })
      .then((data) => {
        setValidation(data);
        setName(data.email);
      })
      .catch((err) => setValidationError(err instanceof Error ? err.message : "Invalid invitation"))
      .finally(() => setValidating(false));
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await register(validation?.email ?? name, validation?.email ?? name, password, token);
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
          <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">Join your team</h1>
        </div>
        <Card className="p-6">
          {validating ? (
            <p className="text-sm text-zinc-500">Validating invitation…</p>
          ) : validationError ? (
            <div className="space-y-4">
              <ErrorNote message={validationError} />
              <Link to="/login" className="block text-center text-sm font-medium text-indigo-600 hover:underline">
                Back to sign in
              </Link>
            </div>
          ) : validation ? (
            <form onSubmit={submit} className="space-y-4">
              <p className="rounded-lg bg-indigo-50 px-3.5 py-2.5 text-sm text-indigo-900 dark:bg-indigo-950 dark:text-indigo-200">
                You have been invited to join <strong>{validation.team_name}</strong> as{" "}
                <strong>{validation.role}</strong> with the email <strong>{validation.email}</strong>.
              </p>
              {error && <ErrorNote message={error} />}
              <Field label="Your name">
                <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Rivera" />
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
                Join {validation.team_name}
              </Button>
            </form>
          ) : (
            <div className="space-y-4">
              <ErrorNote message="This page needs a valid invitation link (…/join?token=…)." />
              <Link to="/login" className="block text-center text-sm font-medium text-indigo-600 hover:underline">
                Back to sign in
              </Link>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
