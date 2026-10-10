# Frontend development guide (Mark IX)

React 19, TypeScript, Vite, Tailwind and TanStack Query. The UI is monochrome and dark by
default. The design language, tokens and component inventory live in
`plan/INSIGHT_mark_ix_design.md`; this file is the how-to. Never introduce colour fills, gradients,
pastel chips or coloured status dots: status is a glyph plus a word (`StatusGlyph`).

## Layout of `frontend/src`

| Folder | What lives there |
| --- | --- |
| `pages/` | One component per route (`App.tsx` has the route table). |
| `components/layout/` | The shell: `AppShell`, `TopBar` (wordmark, slash nav, theme toggle), `QuickSwitcher` (Cmd/Ctrl+K). |
| `components/ui/` | The primitives: `Button`, `TextLink`, `Chip`/`FilterChip`, `StatusGlyph`, `Tabs`, `Table`, `Row`, `Input`/`Textarea`/`Select`, `Dialog`, `Sheet`, `Toaster`, `Skeleton`, `Kbd`, `PageHeader`/`Page`. Import them from `components/ui`. |
| `components/states/` | `LoadingState`, `EmptyState`, `ErrorState`, `Notice`. Every async view uses these. |
| `components/reader/`, `components/ops/` | The reader (feed, rail, toolbar) and the ingestion/health parts. |
| `hooks/` | Query and mutation hooks (`useFeed`, `usePost`, `useReaderMutations`, `useSourcesHealth`, `useIngestionRun`, ...). |
| `lib/` | Pure logic with unit tests (`node --test`): navigation, labels, formatting, run reports. |
| `services/api.ts` | The API client and its types. `services/ApiContext.tsx` provides it (`useApi()`). |
| `test/` | `renderWithProviders`, the fake API and the vitest setup. |

## Adding a feature

1. **Types and the API method** in `services/api.ts`. Mark IX methods throw an `ApiError`
   (`lib/apiError.ts`) instead of returning `{success: false}`. Background jobs are polled with
   `lib/jobPolling.ts`.
2. **A hook** in `hooks/` that reads the client through `useApi()` and wraps it in `useQuery` or
   `useMutation`. Export the query key as a constant, so invalidation is greppable:

   ```ts
   export const SOURCES_HEALTH_KEY = ['sources-health'] as const;

   export function useSourcesHealth() {
     const api = useApi();
     return useQuery({ queryKey: [...SOURCES_HEALTH_KEY], queryFn: () => api.getSourcesHealth(), staleTime: 30_000 });
   }
   ```

3. **The component** renders the four states with the shared parts:

   ```tsx
   const health = useSourcesHealth();
   if (health.isPending) return <LoadingState label="Loading sources" />;
   if (health.isError) return <ErrorState error={health.error} onRetry={() => health.refetch()} />;
   if (!health.data.rows.length) return <EmptyState title="No sources yet" />;
   ```

4. **Pure logic** goes in `lib/` with a `*.test.ts` next to it. Components get a `*.test.tsx`
   rendered with `renderWithProviders` and a fake API through `ApiProvider`.
5. **Lists and rows** ship worst / empty / one / huge fixtures behind the dev-only `?data=` switch
   (`components/ops/DevDataSwitch.tsx`), and are checked at 375px. Import fixture data lazily
   behind `import.meta.env.DEV` (see `ReaderPage`'s `useDevFeedFixture`), so it never ships in the
   production bundle; only the names live in a small module.
6. **Query keys** are exported constants (`FEED_ROOT_KEY`, `UNREAD_COUNTS_KEY`,
   `SOURCES_HEALTH_KEY`, `FOLDERS_KEY`, `postKey`), never repeated as string literals. A failed
   background refetch keeps the loaded data on screen with a notice; only a failed first load
   renders `ErrorState`.

## Styling

- Use the tokens (`bg-surface`, `bg-raised`, `text-fg`, `text-fg-2`, `text-fg-3`, `border-line`,
  `border-line-strong`, `bg-inverse`/`text-inverse-fg`), never literal colours or `rgba()`.
- Pages use `<Page width="reading|ops">` and `<PageHeader title meta actions>`. One primary
  (inverted) button per view.
- Buttons: `<Button variant="primary|secondary|ghost|danger" size="sm|md|lg|icon">`. Icon-only
  buttons need an `aria-label`; `icon` gives a 44px hit area on touch. `danger` is the inverted
  block with an inner hairline and a leading "×" (added by `<Button>`), so it never looks like the
  primary action.
- Destructive actions (delete a source or folder, force a full run, mark all read) confirm first
  with `components/ops/ConfirmDialog.tsx` (or a `Dialog` with a `danger` button), and the dialog
  says what cascades (deleting a track also deletes its experts and its milestone lanes).
- Dialogs, key caps and switches: `Dialog`/`DialogContent`, `Kbd` and `Switch` from
  `components/ui`; never a hand-built overlay, `<kbd>` or `role="switch"` button.
- Sticky chrome under the top bar says so in markup: `sticky top-topbar` (and
  `h-[calc(100dvh-var(--topbar-h))]` for a full-height rail), not a CSS override.
- Toasts: `sonner` through `components/ui/Toaster`, monochrome. Say the outcome and link to the job.
- Motion: short (under 200ms), ease-out, nothing on actions repeated many times a day, and
  fade-only under `prefers-reduced-motion`.
- Source names: always `sourceLabel()` (`lib/sourceLabel.ts`), never a raw feed URL.

## Accessibility

Semantic HTML first; every control reachable and visible on keyboard focus; `aria-current` on the
active nav item; live regions for counts that change; single-key shortcuts can be switched off in
the `?` help (WCAG 2.1.4).

## Commands

```bash
cd frontend
npm run dev         # Vite on :5173, proxies /api to :8000
npm run typecheck
npm test            # node --test for lib/, then vitest
npx eslint <touched files>
npm run build
```
