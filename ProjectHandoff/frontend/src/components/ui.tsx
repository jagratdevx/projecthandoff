import { useEffect, useRef } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { AlertTriangle, Loader2, X } from "lucide-react";
import type { Priority, TaskStatus, HandoverStatus, ProjectStatus, Role, EventStatus } from "../api/types";

// ------------------------------------------------------------------ Buttons

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-600 text-white shadow-sm ring-1 ring-inset ring-white/10 hover:bg-brand-700 focus-visible:ring-brand-500 disabled:hover:bg-brand-600",
  secondary:
    "border border-stone-300/90 bg-white text-stone-700 shadow-sm hover:border-stone-400 hover:bg-stone-50 focus-visible:ring-stone-400 dark:border-stone-700 dark:bg-stone-900 dark:text-stone-200 dark:hover:border-stone-600 dark:hover:bg-stone-800",
  danger:
    "bg-red-600 text-white shadow-sm ring-1 ring-inset ring-white/10 hover:bg-red-700 focus-visible:ring-red-500",
  ghost:
    "text-stone-600 hover:bg-stone-200/60 hover:text-stone-900 focus-visible:ring-stone-400 dark:text-stone-400 dark:hover:bg-stone-800 dark:hover:text-stone-100",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  loading?: boolean;
}

export function Button({ variant = "primary", loading, className = "", children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#f6f5f2] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60 disabled:active:translate-y-0 dark:focus-visible:ring-offset-stone-950 sm:min-h-0 ${BUTTON_VARIANTS[variant]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ Inputs

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`input-base ${props.className ?? ""}`} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`input-base ${props.className ?? ""}`} rows={props.rows ?? 3} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`input-base ${props.className ?? ""}`} />;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-stone-700 dark:text-stone-300">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs text-stone-500 dark:text-stone-400">{hint}</span>}
    </label>
  );
}

// ------------------------------------------------------------------ Cards / layout atoms

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`card-base ${className}`}>{children}</div>;
}

export function CardHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-200/80 px-5 py-4 dark:border-stone-800/80">
      <h2 className="min-w-0 text-sm font-semibold tracking-tight text-stone-900 dark:text-stone-100">{title}</h2>
      {action && <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold leading-[1.15] tracking-[-0.02em] text-stone-900 dark:text-stone-50 sm:text-[30px]">
          {title}
        </h1>
        {subtitle && <p className="mt-1.5 text-sm text-stone-500 dark:text-stone-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ Badges

const STATUS_STYLES: Record<string, string> = {
  "Not Started": "bg-stone-100 text-stone-600 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-400/20",
  "In Progress": "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-400/20",
  Blocked: "bg-red-50 text-red-700 ring-red-600/15 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/20",
  "Under Review": "bg-amber-50 text-amber-700 ring-amber-600/15 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20",
  Completed: "bg-emerald-50 text-emerald-700 ring-emerald-600/15 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/20",
  Low: "bg-stone-100 text-stone-600 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-400/20",
  Medium: "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-400/20",
  High: "bg-amber-50 text-amber-700 ring-amber-600/15 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20",
  Critical: "bg-red-50 text-red-700 ring-red-600/15 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/20",
  Planning: "bg-stone-100 text-stone-600 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-400/20",
  Active: "bg-brand-50 text-brand-700 ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300 dark:ring-brand-400/20",
  "On Hold": "bg-amber-50 text-amber-700 ring-amber-600/15 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20",
  Archived: "bg-stone-100 text-stone-500 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-400 dark:ring-stone-400/20",
  Cancelled: "bg-stone-100 text-stone-500 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-400 dark:ring-stone-400/20",
  owner: "bg-brand-50 text-brand-700 ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300 dark:ring-brand-400/20",
  admin: "bg-violet-50 text-violet-700 ring-violet-600/15 dark:bg-violet-500/10 dark:text-violet-300 dark:ring-violet-400/20",
  coordinator: "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-400/20",
  member: "bg-stone-100 text-stone-600 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-400/20",
  pending: "bg-amber-50 text-amber-700 ring-amber-600/15 dark:bg-amber-500/10 dark:text-amber-300 dark:ring-amber-400/20",
  clarification_requested: "bg-blue-50 text-blue-700 ring-blue-600/15 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-400/20",
  accepted: "bg-emerald-50 text-emerald-700 ring-emerald-600/15 dark:bg-emerald-500/10 dark:text-emerald-300 dark:ring-emerald-400/20",
  rejected: "bg-red-50 text-red-700 ring-red-600/15 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/20",
};

export function Badge({ value, className = "" }: { value: string; className?: string }) {
  const style =
    STATUS_STYLES[value] ??
    "bg-stone-100 text-stone-600 ring-stone-500/15 dark:bg-stone-800 dark:text-stone-300 dark:ring-stone-400/20";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset ${style} ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
      {value.replace(/_/g, " ")}
    </span>
  );
}

// ------------------------------------------------------------------ Progress

export function ProgressBar({ completed, total, className = "" }: { completed: number; total: number; className?: string }) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-stone-200/80 dark:bg-stone-800">
        <div className="h-full rounded-full bg-brand-600 transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-stone-500 dark:text-stone-400">{pct}%</span>
    </div>
  );
}

// ------------------------------------------------------------------ Modal

export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const backdropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-stone-950/40 p-4 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === backdropRef.current) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className={`card-base max-h-[90vh] w-full overflow-y-auto shadow-card-hover ${wide ? "max-w-2xl" : "max-w-md"} p-5`}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold tracking-tight text-stone-900 dark:text-stone-50">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-stone-500 transition hover:bg-stone-100 hover:text-stone-900 dark:hover:bg-stone-800 dark:hover:text-stone-100"
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Confirm",
  destructive = true,
  loading = false,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  destructive?: boolean;
  loading?: boolean;
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="flex items-start gap-3">
        {destructive && <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" aria-hidden />}
        <p className="text-sm text-stone-600 dark:text-stone-300">{message}</p>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button variant={destructive ? "danger" : "primary"} onClick={onConfirm} loading={loading}>
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ States

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-stone-300/90 bg-white/50 px-6 py-14 text-center dark:border-stone-700 dark:bg-stone-900/40">
      {icon && (
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-stone-100 text-stone-400 dark:bg-stone-800 dark:text-stone-500">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold text-stone-900 dark:text-stone-100">{title}</p>
      {description && <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-stone-500 dark:text-stone-400">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return <Loader2 className={`h-5 w-5 animate-spin text-stone-400 ${className}`} aria-hidden />;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-stone-200/70 dark:bg-stone-800/70 ${className}`} />;
}

export function SkeletonList({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-14 w-full" />
      ))}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700 dark:border-red-900/70 dark:bg-red-950/50 dark:text-red-200">
      {message}
    </div>
  );
}

// ------------------------------------------------------------------ Tabs

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; count?: number }[];
  value: T;
  onChange: (id: T) => void;
}) {
  return (
    <div className="inline-flex max-w-full gap-1 overflow-x-auto rounded-xl bg-stone-200/60 p-1 ring-1 ring-inset ring-stone-200/70 dark:bg-stone-800/60 dark:ring-stone-700/60" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
          className={`flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition ${
            value === tab.id
              ? "bg-white text-stone-900 shadow-sm dark:bg-stone-700 dark:text-stone-50"
              : "text-stone-500 hover:text-stone-800 dark:text-stone-400 dark:hover:text-stone-200"
          }`}
        >
          {tab.label}
          {tab.count !== undefined && tab.count > 0 && (
            <span className="rounded-full bg-stone-200 px-1.5 text-xs tabular-nums text-stone-600 dark:bg-stone-600 dark:text-stone-200">
              {tab.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Avatar({ name, className = "" }: { name: string; className?: string }) {
  const text = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <div
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700 ring-1 ring-inset ring-brand-600/10 dark:bg-brand-500/15 dark:text-brand-200 dark:ring-brand-400/20 ${className}`}
      aria-hidden
    >
      {text || "?"}
    </div>
  );
}

export type { Priority, TaskStatus, HandoverStatus, ProjectStatus, Role, EventStatus };
