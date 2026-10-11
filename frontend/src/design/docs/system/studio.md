```meta
kind: system
```

# Design studio

How `/design` works and how a design change moves through it. Implements P9: a design rule lives once, in these files, and a layout idea is tried as a prototype, never on the real page. Spec: `plan/INSIGHT_design_studio_plan.md` (D6 and the prototype verdict).

## Modes

`/design`, reached from ⌘K only, never from the top bar. A sticky 3rem header under the top bar holds the `handbook / wall / bench` segmented control: `?mode=` switches them, and ← → step through them unless a field has focus. The Handbook's URLs: `/design` (principles), `/design/system/:doc`, `/design/components/:name`, `/design/pages/:page`, `/design/parked/:page`, `/design/decisions`, `/design/prototypes/:id`; a frame's own is `/design/frame/:page/:state` (D4).

- **Handbook** (the default): the rail (studio · pages · prototypes · parked) beside the centred doc, with a specimen frame under each page doc and its state / width / theme controls.
- **Wall** (`?mode=wall`): the whole site as one wall (`wall/siteMap.ts`): eleven pages in use at their normal state, in navigation order (feed left, what it opens to its right), each a frame card captioned with its name (a link to its page doc), route and the P-numbers its doc cites. Quiet `border-strong` lines with arrowheads join them, each labelled on a pill by what moves you ("click a title", "source name", "⌘K"); a move to the next column curves through the gutter, across two columns it runs over the top. Above: P1–P12 chips (hover previews, a click keeps it in `?p=`; the pages whose doc cites it stay lit and outlined, the rest dim to 22%, and the rule and "n of 11 pages" show under the bar), `fixtures / live` (`?data=`) and `dark / light` (`?theme=`) for every frame, zoom out / fit (with the %) / in, and the `walk` toggle (`?walk=1`).
- **Walk** (the Wall's right 52%, `wall/walk.ts`): one 1280 × 800 interactive frame on fixtures replaying feed → post → back → source feed → source name → Sources sheet → close → ⌘K track → feed with real clicks and keys, at real speed with a 1.2s beat on each page; restart / play-pause / step icons, a status line (glyph + words, a failed step says why) and the eight steps with the current one inverted. The move being walked is drawn in `text` at 2.5px with an inverted label, its page outlined.
- **Bench:** the checkout for every new design feature. Two large frames side by side, the current page against a prototype (or one state of a page against another), sharing a state, a width (1400 / 390 / 320) and a theme. Everything is in the URL: `?mode=bench&subject=<id|page>&state=&left=&right=&width=&theme=&doc=hide`. On phones the panes stack.

### Wall keys and motion

- Drag or scroll to pan, pinch or ⌘/Ctrl-scroll to zoom about the pointer (10–150%); on the focused map `+` `-` zoom and `0` fits. The view fits the wall until you move it, also when the walk panel opens. Frames are pictures (`pointer-events: none`) except the walk's.
- The map pans and zooms with one `transform`, written per pointer event without React (1:1, no easing); buttons and `0` ease it in 240ms ease-out, instant under reduced motion. Only frames within 240px of the viewport mount, then stay. The walk's map highlight never animates; the pages inside the frame follow their own reduced-motion rules (P12).
- Decisions: 012 three modes, 013 frames inside the real shell, 014 the Wall (`../decisions.md`).

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
