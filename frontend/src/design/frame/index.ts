/**
 * The frame API the studio's modes use (Design Studio D4, S3):
 * - `<Frame page state width height theme data interactive />`: a specimen;
 *   with `prototype=<id>` it shows that prototype on the page's state (D6).
 * - `frameScenarios(page?)` / `frameScenario(page, state)`: the state matrix,
 *   each with its label, the app URL it opens and its suggested width.
 * - `frameUrl(page, state, { theme, data })`: the chromeless route itself;
 *   `prototypeFrameUrl(id, state, …)` is `/design/frame/prototype/:id/:state`.
 * A frame marks `html[data-frame-ready]` once its scenario's steps ran
 * (`true`, or `failed`), for screenshots (S6).
 */
export { default as Frame, type FrameProps } from './Frame';
export { frameUrl, prototypeFrameUrl, type FrameTheme } from './frameUrl';
export type { FrameData } from './transport';
export { FRAME_PAGES, frameScenario, frameScenarios, type FrameScenario } from '../fixtures/scenarios';
