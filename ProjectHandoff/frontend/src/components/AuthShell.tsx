import type { ReactNode } from "react";
import { ArrowLeftRight, ListChecks, Users } from "lucide-react";

const PILLARS = [
  { icon: ArrowLeftRight, text: "Structured handovers with full context" },
  { icon: ListChecks, text: "One source of truth for tasks and deadlines" },
  { icon: Users, text: "Clear ownership across every team" },
];

/**
 * Shared frame for the signed-out screens. On wide viewports it pairs the form
 * with a quiet brand panel; on phones it collapses to a single centred column.
 */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-[#f6f5f2] dark:bg-stone-950">
      <aside className="relative hidden w-[44%] max-w-xl shrink-0 flex-col justify-between overflow-hidden bg-brand-950 p-12 text-white lg:flex">
        <div className="pointer-events-none absolute -right-28 -top-28 h-96 w-96 rounded-full bg-brand-500/25 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-brand-400/10 blur-3xl" aria-hidden />

        <div className="relative flex items-center gap-3">
          <img src="/logo.png" alt="" className="h-10 w-10 rounded-xl ring-1 ring-inset ring-white/15" />
          <span className="text-[15px] font-semibold tracking-tight">ProjectHandoff</span>
        </div>

        <div className="relative max-w-md">
          <p className="eyebrow text-brand-300">Continuity, by design</p>
          <h2 className="mt-4 text-[32px] font-semibold leading-[1.15] tracking-[-0.02em]">
            Work changes hands. Context shouldn’t disappear.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-brand-100/70">
            A calm, shared workspace for teams that hand work between people — without losing the thread.
          </p>
          <ul className="mt-8 space-y-3.5">
            {PILLARS.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3 text-sm text-brand-50/90">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 ring-1 ring-inset ring-white/10">
                  <Icon className="h-4 w-4" aria-hidden />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-brand-200/50">Built for teams that share the work.</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-7">
            <div className="mb-5 flex h-10 w-10 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-inset ring-stone-900/5 dark:bg-stone-900 dark:ring-white/10 lg:hidden">
              <img src="/logo.png" alt="ProjectHandoff" className="h-7 w-7 rounded-md" />
            </div>
            <h1 className="text-2xl font-semibold tracking-[-0.02em] text-stone-900 dark:text-stone-50">{title}</h1>
            {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-stone-500 dark:text-stone-400">{subtitle}</p>}
          </div>

          {children}

          {footer && <div className="mt-6 text-center text-sm text-stone-500 dark:text-stone-400">{footer}</div>}
        </div>
      </main>
    </div>
  );
}
