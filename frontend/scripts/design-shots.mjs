// Screenshots of every frame (Design Studio D9), for before/after reviews; not committed.
//   npm run design:shots                          every page × state, and every prototype × its states, at 1400 and 390
//                                                 (and a state's own width, the 320px top bar), dark and light; then the
//                                                 studio itself (Handbook, Wall, Bench) at 1400: --page studio

//   npm run design:shots -- --page reader --state error,worst --theme light --width 390
//   npm run design:shots -- --base-url http://localhost:5173   shoot a server already running (else one starts on 5198 or the next free port)
// Writes .design-shots/<page>/<state>.<width>.<theme>.png. Fails when a frame never marks
// html[data-frame-ready], shows the unmocked-request bar, or logs an error, and when no shot matches.
// Playwright is not a dependency: it resolves from ~/.cache/insight-pw-scripts (INSIGHT_PW_SCRIPTS)
// and uses the dedicated browser in ~/.cache/insight-pw (PLAYWRIGHT_BROWSERS_PATH).
import { mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createServer } from 'vite';

import { frameHeight } from '../src/design/frame/frameUrl.ts';
import { parseShotArgs, shotList } from '../src/lib/designShots.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, '.design-shots');
const READY_MS = 20_000;
const WORKERS = 4;

let args;
try {
  args = parseShotArgs(process.argv.slice(2));
} catch (error) {
  console.error(`design shots: ${error.message}`);
  process.exit(2);
}
process.env.PLAYWRIGHT_BROWSERS_PATH ??= join(homedir(), '.cache', 'insight-pw');
const scripts = process.env.INSIGHT_PW_SCRIPTS ?? join(homedir(), '.cache', 'insight-pw-scripts');
const { chromium } = (await import(pathToFileURL(createRequire(join(scripts, 'package.json')).resolve('playwright')).href)).default;

// Vite loads the state matrix (aliases, import.meta.glob) and, without --base-url, serves the frames.
const started = Date.now();
const vite = await createServer({
  root,
  logLevel: 'error',
  server: args.baseUrl ? { middlewareMode: true, hmr: false } : { host: '127.0.0.1', port: args.port, strictPort: false, hmr: false },
});
const failed = [];
let shots = [];
let retried = 0;
let fatal = null;
try {
  const { frameScenarios } = await vite.ssrLoadModule('/src/design/fixtures/scenarios.ts');
  const { PROTOTYPES } = await vite.ssrLoadModule('/src/design/prototypeRegistry.ts');
  shots = shotList({ scenarios: frameScenarios(), prototypes: PROTOTYPES }, args.filters);
  if (!args.baseUrl) await vite.listen();
  const base = args.baseUrl ?? vite.resolvedUrls.local[0].replace(/\/$/, '');
  console.log(`design shots: ${shots.length} frames from ${base} into .design-shots/`);
  if (!shots.length) throw new Error('no shot matches the filters');

  for (const shot of shots) rmSync(join(out, shot.file), { force: true });
  const browser = await chromium.launch();
  const queue = [...shots];
  const worker = async () => {
    for (let shot = queue.shift(); shot; shot = queue.shift()) {
      // A cold dev server may reload while it optimizes dependencies: one retry before a frame fails.
      let problems = await take(browser, base, shot);
      if (problems.length) {
        problems = await take(browser, base, shot);
        retried += 1;
      }
      if (problems.length) failed.push({ shot, problems });
      process.stdout.write(problems.length ? 'x' : '.');
    }
  };
  await Promise.all(Array.from({ length: WORKERS }, worker));
  await browser.close();
} catch (error) {
  fatal = error;
} finally {
  await vite.close();
}
if (fatal) {
  console.error(`design shots: ${fatal.message}`);
  process.exit(1);
}

const seconds = ((Date.now() - started) / 1000).toFixed(1);
console.log(`\n${shots.length - failed.length}/${shots.length} frames shot in ${seconds}s${retried ? ` (${retried} retried)` : ''}`);
for (const { shot, problems } of failed) console.error(`  ${shot.file}\n    ${problems.join('\n    ')}`);
process.exit(failed.length ? 1 : 0);

/** Every frame in the page: the page itself, or the iframes a studio page holds. */
function frameDocuments(shot) {
  return shot.studio
    ? '[...document.querySelectorAll("iframe")].map((frame) => frame.contentDocument?.documentElement ?? null)'
    : '[document.documentElement]';
}

/** One shot: open it, wait for its frames to be ready, check their request bars, save the PNG. Returns what went wrong. */
async function take(browser, base, shot) {
  const page = await browser.newPage({ viewport: { width: shot.width, height: shot.studio ? 900 : frameHeight(shot.width) } });
  const problems = [];
  // The studio page itself follows the app's stored theme; its frames take theirs from the URL.
  if (shot.studio) await page.addInitScript((theme) => localStorage.setItem('insight.theme', theme), `theme-${shot.theme}`);
  page.on('pageerror', (error) => problems.push(`page error: ${error.message}`));
  page.on('console', (message) => {
    const url = message.location().url ?? '';
    // Expected: a worst case's broken image points at a `.invalid` host (RFC 2606), and the API
    // client logs each failed read, which error states make on purpose (unmocked ones show in the bar).
    // The studio around the frames talks to the real API, which a shot run need not have.
    if (message.type() !== 'error' || /^https?:\/\/[^/]+\.invalid\//.test(url) || url.endsWith('/src/services/api.ts')) return;
    if (shot.studio && new URL(url || base, base).pathname.startsWith('/api/')) return;
    problems.push(`console error: ${message.text().split('\n')[0]} (${url})`);
  });
  try {
    await page.goto(`${base}${shot.url}`);
    if (shot.studio) await page.waitForSelector('.design-studio', { timeout: READY_MS });
    const docs = frameDocuments(shot);
    await page.waitForFunction(`${docs}.every((root) => root?.dataset.frameReady)`, null, { timeout: READY_MS });
    const states = await page.evaluate(`${docs}.map((root) => root.dataset.frameReady)`);
    if (states.some((state) => state !== 'true')) problems.push('the scenario setup failed');
    await page.evaluate(() => document.fonts.ready);
    // The bar renders from the report a frame after the last request; let it paint before reading it.
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const bars = await page.evaluate(`${docs}.map((root) => root.querySelector('[aria-label="Frame requests"]')?.innerText ?? '').join('\\n')`);
    problems.push(...bars.split('\n').filter((line) => /^(unmocked request|frame setup failed)/.test(line)));
  } catch (error) {
    problems.push(`not ready: ${error.message.split('\n')[0]}`);
  }
  mkdirSync(dirname(join(out, shot.file)), { recursive: true });
  await page.screenshot({ path: join(out, shot.file), fullPage: !shot.studio, animations: 'disabled' }).catch((error) => problems.push(`screenshot: ${error.message}`));
  await page.close();
  return problems;
}
