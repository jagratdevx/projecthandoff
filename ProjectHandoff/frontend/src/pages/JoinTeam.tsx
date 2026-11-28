import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useAuth } from "../state/AuthContext";
import { AuthShell } from "../components/AuthShell";
import { Button, Card, ErrorNote, Field, Input } from "../components/ui";

interface ValidateResponse {
  team_name: string;
  team_id: string;
  role: string;
  email: string;
  subteam_id?: string;
  subteam_name?: string;
  subteam_role?: string;
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
    <AuthShell
      title="Join your team"
      subtitle="Finish setting up your account to accept the invitation."
      footer={
        <Link to="/login" className="link-accent">
          Back to sign in
        </Link>
      }
    >
      <Card className="p-6 shadow-card-hover sm:p-7">
        {validating ? (
          <p className="text-sm text-stone-500 dark:text-stone-400">Validating invitation…</p>
        ) : validationError ? (
          <ErrorNote message={validationError} />
        ) : validation ? (
          <form onSubmit={submit} className="space-y-4">
            <p className="rounded-xl bg-brand-50 px-3.5 py-3 text-sm leading-relaxed text-brand-900 ring-1 ring-inset ring-brand-600/10 dark:bg-brand-500/10 dark:text-brand-200 dark:ring-brand-400/20">
              You have been invited to join <strong className="font-semibold">{validation.team_name}</strong> as{" "}
              <strong className="font-semibold">{validation.role}</strong>
              {validation.subteam_name && (
                <>
                  , <strong className="font-semibold">{validation.subteam_role ?? "volunteer"}</strong> in{" "}
                  <strong className="font-semibold">{validation.subteam_name}</strong>
                </>
              )}{" "}
              with the email <strong className="font-semibold">{validation.email}</strong>.
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
            <Button type="submit" loading={loading} className="mt-1 w-full">
              Join {validation.team_name}
            </Button>
          </form>
        ) : (
          <ErrorNote message="This page needs a valid invitation link (…/join?token=…)." />
        )}
      </Card>
    </AuthShell>
  );
}
