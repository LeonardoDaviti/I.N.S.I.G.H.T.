```meta
kind: system
```

# Design studio

How `/design` works and how a design change moves through it. Implements P9: a design rule lives once, in these files, and a layout idea is tried as a prototype, never on the real page. Spec: `plan/INSIGHT_design_studio_plan.md` (D6 and the prototype verdict).

## Modes

`?mode=` switches them; ← → step through them unless a field has focus.

- **Handbook** (the default): the rail, the docs and a specimen frame under each page doc.
- **Wall:** the whole site as one site map, every page at its normal state.
- **Bench:** the checkout for every new design feature. Two large frames side by side, the current page against a prototype (or one state of a page against another), sharing a state, a width (1400 / 390 / 320) and a theme. Everything is in the URL: `?mode=bench&subject=<id|page>&state=&left=&right=&width=&theme=&doc=hide`. On phones the panes stack.

## Prototypes

A prototype is a folder `src/design/prototypes/<yyyy-mm-dd>-<slug>/`. The glob registers it, so there is no list to edit.

- **`README.md`** opens with a `meta` block, then says what changes and what to compare:
  - `hypothesis:` one sentence the comparison should prove or disprove;
  - `principles:` the P-numbers it serves;
  - `page:` the page doc it compares against, and `states:` the states to compare on (the first is Bench's default);
  - `status:` draft, review, accepted or rejected;
  - `created:` the folder's date.
- **`index.tsx`** default-exports a component that receives the real page (its routes, inside the shell, on the frame's fixtures) as `children`. An override wraps them, for example with one CSS rule. A replacement renders something else and may import anything from the app.
- **`doc.diff`** (optional): the change to the page doc if the prototype is accepted, as a unified diff. Bench shows it in the drawer.

It renders at `/design/frame/prototype/<id>/<state>`, on the same fixtures, theme and width as the real page's frame (D4). It never touches a production page and never calls the live API. `coverage.test.ts` fails when a README's meta is incomplete, cites a principle that does not exist, or names a page or state with no page doc and frame scenario.

## Lifecycle (D6)

`draft → review → accepted | rejected`. The studio writes nothing, because the docs are files. Bench's drawer shows the exact line to give the agent, with a copy button:

- **`accept prototype <id>`:** in one commit, the agent ports the change into the real page and its page doc (as `doc.diff` says), deletes the folder and adds a line to the decisions log.
- **`reject prototype <id>: <reason>`:** the agent deletes the folder, and the decisions log keeps one line with the reason.

Draft and review are open. The Handbook rail and Bench's picker list open prototypes first, with their status and age, so nothing rots silently.

## Screenshots (D9)

`npm run design:shots` writes every page × state (the frame scenarios) and every prototype × its states, at 1400 and 390, dark and light, to `frontend/.design-shots/<page>/<state>.<width>.<theme>.png` (prototypes under `prototypes/<id>/`). It is git-ignored: shoot before and after a change and compare.

- It starts its own dev server on 5198 (or the next free port) and stops it; `--base-url <url>` shoots a running one instead.
- Filters take comma lists: `--page reader,prototypes --state error --width 390 --theme light`.
- A frame fails, and the run exits non-zero, when it never marks `html[data-frame-ready]`, shows the unmocked-request bar or logs a console error.
- Playwright is not a dependency: it resolves from `~/.cache/insight-pw-scripts` (`INSIGHT_PW_SCRIPTS`) with the browser in `~/.cache/insight-pw`.
