import { useState } from "react";
import { Link } from "react-router-dom";
import { CalendarDays, Plus } from "lucide-react";
import { api } from "../api/client";
import type { Event } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useToast } from "../state/ToastContext";
import { Badge, Button, EmptyState, Field, Input, Modal, PageHeader, ProgressBar, Select, SkeletonList, Textarea } from "../components/ui";
import { formatDate } from "../lib/format";

const EMPTY_FORM = { name: "", description: "", start_date: "", end_date: "", status: "Planning" };

export function Events() {
  const toast = useToast();
  const { data, loading, error, reload } = useResource<Event[]>(() => api("/api/events"), [], 15000);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await api("/api/events", { method: "POST", body: form });
      toast.push("success", "Event created");
      setCreateOpen(false);
      setForm(EMPTY_FORM);
      void reload();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to create event");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Events"
        subtitle="School events and competitions, organized by department"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden /> New event
          </Button>
        }
      />

      {loading && !data ? (
        <SkeletonList rows={3} />
      ) : error ? (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          icon={<CalendarDays className="h-10 w-10" aria-hidden />}
          title="No events planned yet"
          description="Create your first event — a science fair, sports day, or competition — and organize it into departments."
          action={
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden /> New event
            </Button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {(data ?? []).map((event) => (
            <Link key={event.event_id} to={`/events/${event.event_id}`} className="card-base block p-5 transition hover:border-indigo-300 dark:hover:border-indigo-700">
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-zinc-900 dark:text-zinc-50">{event.name}</p>
                <Badge value={event.status} />
              </div>
              <p className="mt-0.5 line-clamp-2 text-sm text-zinc-500 dark:text-zinc-400">{event.description || "No description"}</p>
              <p className="mt-2 text-xs text-zinc-500">
                {event.start_date ? formatDate(event.start_date) : "TBD"}
                {event.end_date ? ` → ${formatDate(event.end_date)}` : ""}
              </p>
              <ProgressBar completed={event.progress?.completed ?? 0} total={event.progress?.total ?? 0} className="mt-3" />
            </Link>
          ))}
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create event">
        <form onSubmit={create} className="space-y-4">
          {formError && <p className="text-sm text-red-600 dark:text-red-400">{formError}</p>}
          <Field label="Name">
            <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Regional Robotics Final" />
          </Field>
          <Field label="Description">
            <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Start date">
              <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
            </Field>
            <Field label="End date">
              <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
            </Field>
          </div>
          <Field label="Status">
            <Select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {["Planning", "Active", "Completed", "Cancelled"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </Select>
          </Field>
          <div className="flex justify-end gap-2 pt-2">
            <Button type="button" variant="secondary" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Create event
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
