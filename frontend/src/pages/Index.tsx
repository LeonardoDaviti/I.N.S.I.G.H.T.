import { Link } from 'react-router-dom';
import type { ComponentType } from 'react';
import {
  ArrowRight,
  BarChart3,
  BookOpen,
  Inbox,
  Layers3,
  PlayCircle,
  Settings,
  Sparkles,
  Workflow,
} from 'lucide-react';

type FeatureCard = {
  title: string;
  description: string;
  href: string;
  icon: ComponentType<{ className?: string }>;
  accent: string;
  label: string;
};

const featureCards: FeatureCard[] = [
  {
    title: 'Daily Briefing',
    description: 'Read the standard daily, weekly, and topic briefing surfaces.',
    href: '/briefing',
    icon: BarChart3,
    accent: 'from-blue-500/15 via-blue-500/10 to-transparent',
    label: 'core briefing',
  },
  {
    title: 'Post Intelligence',
    description: 'Open a post and inspect evidence, memory, events, and story links inline.',
    href: '/briefing',
    icon: Sparkles,
    accent: 'from-indigo-500/15 via-indigo-500/10 to-transparent',
    label: 'post detail',
  },
  {
    title: 'Stories',
    description: 'Browse story threads, timelines, anchors, and connected posts.',
    href: '/stories',
    icon: BookOpen,
    accent: 'from-emerald-500/15 via-emerald-500/10 to-transparent',
    label: 'story graph',
  },
  {
    title: 'Analyst Inbox',
    description: 'Review generated candidates, read scoring reasons, and record actions.',
    href: '/inbox',
    icon: Inbox,
    accent: 'from-rose-500/15 via-rose-500/10 to-transparent',
    label: 'triage',
  },
  {
    title: 'Vertical Briefing',
    description: 'Inspect a single source as a collapsed vertical thread with track kinds.',
    href: '/briefing/vertical',
    icon: Layers3,
    accent: 'from-violet-500/15 via-violet-500/10 to-transparent',
    label: 'source view',
  },
  {
    title: 'Source Settings',
    description: 'Tune source metadata, ordering, and enablement.',
    href: '/settings/sources',
    icon: Settings,
    accent: 'from-slate-500/15 via-slate-500/10 to-transparent',
    label: 'operations',
  },
  {
    title: 'Ingestion Control',
    description: 'Run live fetch, archive, logs, and scheduler operations.',
    href: '/ingestion',
    icon: PlayCircle,
    accent: 'from-cyan-500/15 via-cyan-500/10 to-transparent',
    label: 'operations',
  },
];

function WorkspaceCard({ card }: { card: FeatureCard }) {
  return (
    <Link
      to={card.href}
      className="group app-panel relative overflow-hidden p-5 transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_22px_50px_rgba(76,141,255,0.16)]"
    >
      <div className={`absolute inset-0 bg-gradient-to-br ${card.accent} opacity-80`} />
      <div className="relative flex h-full flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="inline-flex h-11 w-11 items-center justify-center rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)]">
            <card.icon className="h-5 w-5 text-[var(--accent-strong)]" />
          </div>
          <span className="rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-[var(--text-faint)]">
            {card.label}
          </span>
        </div>
        <div className="space-y-2">
          <h3 className="text-lg font-semibold text-[var(--text-normal)]">{card.title}</h3>
          <p className="text-sm leading-6 text-[var(--text-muted)]">{card.description}</p>
        </div>
        <div className="mt-auto inline-flex items-center gap-2 text-sm font-medium text-[var(--text-normal)]">
          Open workspace
          <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
        </div>
      </div>
    </Link>
  );
}

export default function Index() {
  const shortcuts = [
    {
      title: 'Inspect a post',
      description: 'Open a post from Daily Briefing and use the intelligence inspector tabs.',
      href: '/briefing',
      icon: Sparkles,
    },
    {
      title: 'Review stories',
      description: 'Track a story from anchor post to updates and post attachments.',
      href: '/stories',
      icon: BookOpen,
    },
    {
      title: 'Triage inbox',
      description: 'Work the backlog of candidate posts and stories without leaving the browser.',
      href: '/inbox',
      icon: Inbox,
    },
    {
      title: 'Read one source',
      description: 'Switch to a vertical briefing and see how one source evolves over time.',
      href: '/briefing/vertical',
      icon: Layers3,
    },
  ];

  return (
    <div className="app-shell min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="app-panel overflow-hidden">
          <div className="grid gap-0 lg:grid-cols-[1.15fr_0.85fr]">
            <div className="relative p-6 sm:p-8 lg:p-10">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(76,141,255,0.16),transparent_40%),radial-gradient(circle_at_bottom_left,rgba(29,78,216,0.10),transparent_30%)]" />
              <div className="relative space-y-5">
                <div className="inline-flex rounded-full border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] px-3 py-1 text-xs uppercase tracking-[0.2em] text-[var(--text-faint)]">
                  INSIGHT workspace
                </div>
                <div className="space-y-3">
                  <h1 className="max-w-3xl text-4xl font-bold tracking-tight text-[var(--text-normal)] sm:text-5xl">
                    Everything we built is now reachable from the browser.
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-[var(--text-muted)] sm:text-base">
                    Use this hub to move between briefing, post intelligence, stories, analyst inbox, and vertical source briefings without calling the API by hand.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Link to="/briefing" className="app-inline-button app-inline-button--primary">
                    <BarChart3 className="h-4 w-4" />
                    Open Daily Briefing
                  </Link>
                  <Link to="/stories" className="app-inline-button">
                    <BookOpen className="h-4 w-4" />
                    Open Stories
                  </Link>
                  <Link to="/inbox" className="app-inline-button">
                    <Inbox className="h-4 w-4" />
                    Open Inbox
                  </Link>
                </div>
              </div>
            </div>

            <div className="border-t border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-6 lg:border-l lg:border-t-0">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
                {shortcuts.map((shortcut) => (
                  <Link
                    key={shortcut.title}
                    to={shortcut.href}
                    className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] p-4 transition hover:border-[var(--accent-strong)] hover:bg-[var(--background-primary-alt)]"
                  >
                    <div className="flex items-start gap-3">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)]">
                        <shortcut.icon className="h-4 w-4 text-[var(--accent-strong)]" />
                      </div>
                      <div>
                        <div className="font-semibold text-[var(--text-normal)]">{shortcut.title}</div>
                        <div className="mt-1 text-sm text-[var(--text-muted)]">{shortcut.description}</div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </header>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {featureCards.map((card) => (
            <WorkspaceCard key={card.title} card={card} />
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="app-panel p-6">
            <div className="mb-4 flex items-center gap-2">
              <Workflow className="h-5 w-5 text-[var(--accent-strong)]" />
              <h2 className="text-lg font-semibold text-[var(--text-normal)]">How to move through the workspace</h2>
            </div>
            <div className="space-y-3 text-sm leading-7 text-[var(--text-muted)]">
              <p>Start with Daily Briefing when you want the broad view, then open any post to inspect evidence, memory, events, and story links.</p>
              <p>Use Stories when you need chronology, the Inbox when you need triage, and Vertical Briefing when you need one source distilled into tracks.</p>
              <p>Use Sources and Ingestion when you need to change input behavior or troubleshoot data flow.</p>
            </div>
          </div>

          <div className="app-panel p-6">
            <div className="mb-4 flex items-center gap-2">
              <PlayCircle className="h-5 w-5 text-[var(--accent-strong)]" />
              <h2 className="text-lg font-semibold text-[var(--text-normal)]">Recommended path</h2>
            </div>
            <div className="space-y-3">
              <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                <div className="text-sm font-semibold text-[var(--text-normal)]">1. Brief the day</div>
                <div className="mt-1 text-sm text-[var(--text-muted)]">Open the daily briefing and scan the posts that matter.</div>
              </div>
              <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                <div className="text-sm font-semibold text-[var(--text-normal)]">2. Inspect the post</div>
                <div className="mt-1 text-sm text-[var(--text-muted)]">Use the post intelligence panel to see the backend evidence stack.</div>
              </div>
              <div className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-secondary)] p-4">
                <div className="text-sm font-semibold text-[var(--text-normal)]">3. Escalate or file</div>
                <div className="mt-1 text-sm text-[var(--text-muted)]">Move to stories, inbox, or vertical briefing depending on the signal.</div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
