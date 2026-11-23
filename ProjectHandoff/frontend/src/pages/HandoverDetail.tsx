import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeftRight, Check, MessageCircleQuestion, Reply, X } from "lucide-react";
import { api } from "../api/client";
import type { Attachment, Comment, Handover, Task } from "../api/types";
import { useResource } from "../hooks/useResource";
import { useAuth } from "../state/AuthContext";
import { useToast } from "../state/ToastContext";
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  Field,
  Modal,
  PageHeader,
  SkeletonList,
  Textarea,
} from "../components/ui";
import { formatDate, timeAgo } from "../lib/format";

interface HandoverDetailData {
  handover: Handover;
  task: Task | null;
  comments: Comment[];
  attachments: Attachment[];
  names: Record<string, string>;
}

function Section({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-5 py-3.5">
      <p className="text-xs font-medium uppercase tracking-wide text-stone-400">{label}</p>
      <p className="mt-1 whitespace-pre-wrap text-sm text-stone-700 dark:text-stone-300">{value || "—"}</p>
    </div>
  );
}

export function HandoverDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const toast = useToast();

  const { data, loading, error, reload } = useResource<HandoverDetailData>(
    () => api(`/api/handovers/${id}`),
    [id],
    15000,
  );

  const [busy, setBusy] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [clarifyOpen, setClarifyOpen] = useState(false);
  const [clarifyQuestion, setClarifyQuestion] = useState("");
  const [respondOpen, setRespondOpen] = useState(false);
  const [respondMessage, setRespondMessage] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);

  if (loading && !data) return <SkeletonList rows={4} />;
  if (error || !data) return <p className="text-sm text-red-600 dark:text-red-400">{error ?? "Handover not found"}</p>;

  const { handover, task, comments, names } = data;
  const isProposedOwner = handover.proposed_owner_id === user?.user_id;
  const isPreviousOwner = handover.previous_owner_id === user?.user_id;
  const isAdmin = user?.role === "owner" || user?.role === "admin";

  const act = async (path: string, body: Record<string, unknown> | undefined, successMessage: string) => {
    setBusy(true);
    try {
      await api(`/api/handovers/${handover.handover_id}/${path}`, { method: "POST", body });
      toast.push("success", successMessage);
      setRejectOpen(false);
      setClarifyOpen(false);
      setRespondOpen(false);
      setCancelOpen(false);
      void reload();
    } catch (err) {
      toast.push("error", err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <button onClick={() => navigate("/handovers")} className="mb-3 text-sm text-stone-500 hover:text-stone-900 dark:hover:text-stone-100">
        ← Back to handovers
      </button>

      <PageHeader
        title={task?.title ?? "Task handover"}
        subtitle={`Handover from ${names[handover.previous_owner_id] ?? "Unknown"} to ${names[handover.proposed_owner_id] ?? "Unknown"}`}
        actions={<Badge value={handover.status} />}
      />

      {handover.status === "pending" && isProposedOwner && (
        <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 dark:border-amber-800 dark:bg-amber-950/50">
          <p className="flex-1 text-sm text-amber-900 dark:text-amber-200">
            You have been asked to take over this task. Review the context below before accepting.
          </p>
          <Button onClick={() => void act("accept", undefined, "Handover accepted — the task is now yours")} loading={busy}>
            <Check className="h-4 w-4" aria-hidden /> Accept
          </Button>
          <Button variant="secondary" onClick={() => { setRejectReason(""); setRejectOpen(true); }}>
            <X className="h-4 w-4" aria-hidden /> Reject
          </Button>
          <Button variant="ghost" onClick={() => { setClarifyQuestion(""); setClarifyOpen(true); }}>
            <MessageCircleQuestion className="h-4 w-4" aria-hidden /> Ask for clarification
          </Button>
        </div>
      )}

      {handover.status === "clarification_requested" && (isPreviousOwner || isAdmin) && (
        <div className="mb-6 flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-5 py-4 dark:border-blue-800 dark:bg-blue-950/50">
          <p className="flex-1 text-sm text-blue-900 dark:text-blue-200">
            {names[handover.proposed_owner_id] ?? "The proposed owner"} asked a question below. Respond to return the
            handover to pending.
          </p>
          <Button onClick={() => { setRespondMessage(""); setRespondOpen(true); }} loading={busy}>
            <Reply className="h-4 w-4" aria-hidden /> Respond
          </Button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Handover context" />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              <Section label="Work already completed" value={handover.completed_work} />
              <Section label="Work remaining" value={handover.remaining_work} />
              <Section label="Current state" value={handover.current_state} />
              <Section label="Blockers" value={handover.blockers} />
              <Section label="Next recommended actions" value={handover.next_actions} />
              <Section label="Relevant files" value={handover.relevant_files} />
              <Section label="Target deadline" value={handover.deadline ? formatDate(handover.deadline) : ""} />
              <div className="px-5 py-3.5">
                <p className="text-xs font-medium uppercase tracking-wide text-stone-400">Timeline</p>
                <p className="mt-1 text-sm text-stone-700 dark:text-stone-300">
                  Sent {formatDate(handover.created_at)}
                  {handover.accepted_at && ` · resolved ${formatDate(handover.accepted_at)}`}
                </p>
              </div>
            </div>
          </Card>

          {task && (
            <Card>
              <CardHeader title="Linked task" />
              <div className="flex items-center justify-between px-5 py-4">
                <div>
                  <p className="text-sm font-medium text-stone-900 dark:text-stone-100">{task.title}</p>
                  <p className="text-xs text-stone-500">
                    Currently assigned to {names[task.assigned_to] ?? "Unknown"} · {task.status}
                  </p>
                </div>
                <Link to={`/tasks/${task.task_id}`}>
                  <Button variant="secondary">Open task</Button>
                </Link>
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="Discussion" />
            <div className="divide-y divide-stone-100 dark:divide-stone-800">
              {comments.length === 0 && (
                <EmptyState
                  icon={<ArrowLeftRight className="h-6 w-6" aria-hidden />}
                  title="No discussion yet"
                  description="Questions, clarifications and decisions about this handover appear here."
                />
              )}
              {comments.map((entry) => (
                <div key={entry.comment_id} className="flex gap-3 px-5 py-3.5">
                  <Avatar name={names[entry.user_id] ?? "Unknown"} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm">
                      <span className="font-medium text-stone-900 dark:text-stone-100">{names[entry.user_id] ?? "Unknown"}</span>{" "}
                      <span className="text-xs text-stone-400">{timeAgo(entry.created_at)}</span>
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-stone-700 dark:text-stone-300">{entry.comment}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Participants" />
            <div className="space-y-3 p-5">
              <div className="flex items-center gap-3">
                <Avatar name={names[handover.previous_owner_id] ?? "Unknown"} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{names[handover.previous_owner_id] ?? "Unknown"}</p>
                  <p className="text-xs text-stone-500">Previous owner</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Avatar name={names[handover.proposed_owner_id] ?? "Unknown"} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{names[handover.proposed_owner_id] ?? "Unknown"}</p>
                  <p className="text-xs text-stone-500">Proposed new owner</p>
                </div>
              </div>
            </div>
          </Card>

          {(isPreviousOwner || isAdmin) && (handover.status === "pending" || handover.status === "clarification_requested") && (
            <Card className="p-5">
              <p className="mb-3 text-sm font-medium text-stone-900 dark:text-stone-100">Handover controls</p>
              {handover.status === "clarification_requested" ? (
                <p className="mb-3 text-sm text-stone-500">Awaiting your clarification response.</p>
              ) : null}
              <div className="space-y-2">
                {handover.status === "pending" && (
                  <Button variant="secondary" className="w-full" onClick={() => setCancelOpen(true)}>
                    Cancel this handover
                  </Button>
                )}
                {handover.status === "clarification_requested" && (
                  <Button className="w-full" onClick={() => { setRespondMessage(""); setRespondOpen(true); }}>
                    Respond to question
                  </Button>
                )}
              </div>
            </Card>
          )}
        </div>
      </div>

      {/* Reject modal */}
      <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject handover">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act("reject", { reason: rejectReason.trim() }, "Handover rejected — ownership unchanged");
          }}
          className="space-y-4"
        >
          <p className="text-sm text-stone-500 dark:text-stone-400">
            The current owner keeps the task. Your reason is posted to the task discussion.
          </p>
          <Field label="Reason *">
            <Textarea required value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="I don't have capacity this month…" />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" variant="danger" loading={busy}>
              Reject handover
            </Button>
          </div>
        </form>
      </Modal>

      {/* Clarify modal */}
      <Modal open={clarifyOpen} onClose={() => setClarifyOpen(false)} title="Ask for clarification">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act("clarify", { question: clarifyQuestion.trim() }, "Clarification requested");
          }}
          className="space-y-4"
        >
          <Field label="Your question *">
            <Textarea required value={clarifyQuestion} onChange={(e) => setClarifyQuestion(e.target.value)} placeholder="Which motor controller is being replaced?" />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setClarifyOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Send question
            </Button>
          </div>
        </form>
      </Modal>

      {/* Respond modal */}
      <Modal open={respondOpen} onClose={() => setRespondOpen(false)} title="Respond to clarification">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void act("respond", { message: respondMessage.trim() }, "Response sent — handover back to pending");
          }}
          className="space-y-4"
        >
          <Field label="Your answer *">
            <Textarea required value={respondMessage} onChange={(e) => setRespondMessage(e.target.value)} placeholder="The spark MAX, not the talon…" />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setRespondOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy}>
              Send response
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        onConfirm={() => void act("cancel", undefined, "Handover cancelled")}
        title="Cancel handover"
        message="Cancel this pending handover? The task stays with you."
        confirmLabel="Cancel handover"
        loading={busy}
      />
    </div>
  );
}
