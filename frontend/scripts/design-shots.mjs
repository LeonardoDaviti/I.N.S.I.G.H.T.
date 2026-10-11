// Screenshots of every frame (Design Studio D9), for before/after reviews; not committed.
//   npm run design:shots                          every page × state, and every prototype × its states, at 1400 and 390, dark and light
//   npm run design:shots -- --page reader --state error,worst --theme light --width 390
//   npm run design:shots -- --base-url http://localhost:5173   shoot a server already running (else one starts on 5198 or the next free port)
// Writes .design-shots/<page>/<state>.<width>.<theme>.png. Fails when a frame never marks
// html[data-frame-ready], shows the unmocked-request bar, or logs an error.
// Playwright is not a dependency: it resolves from ~/.cache/insight-pw-scripts (INSIGHT_PW_SCRIPTS)
// and uses the dedicated browser in ~/.cache/insight-pw (PLAYWRIGHT_BROWSERS_PATH).
import { mkdirSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createServer } from 'vite';

import { parseShotArgs, shotList } from '../src/lib/designShots.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(root, '.design-shots');
const HEIGHT = { 1400: 900, 390: 844 };
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
try {
  const { frameScenarios } = await vite.ssrLoadModule('/src/design/fixtures/scenarios.ts');
  const { PROTOTYPES } = await vite.ssrLoadModule('/src/design/prototypeRegistry.ts');
  shots = shotList({ scenarios: frameScenarios(), prototypes: PROTOTYPES }, args.filters);
  if (!args.baseUrl) await vite.listen();
  const base = args.baseUrl ?? vite.resolvedUrls.local[0].replace(/\/$/, '');
  console.log(`design shots: ${shots.length} frames from ${base} into .design-shots/`);

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
} finally {
  await vite.close();
}

const seconds = ((Date.now() - started) / 1000).toFixed(1);
console.log(`\n${shots.length - failed.length}/${shots.length} frames shot in ${seconds}s${retried ? ` (${retried} retried)` : ''}`);
for (const { shot, problems } of failed) console.error(`  ${shot.file}\n    ${problems.join('\n    ')}`);
process.exit(failed.length ? 1 : 0);

/** One frame: open it, wait for ready, check the request bar, save the PNG. Returns what went wrong. */
async function take(browser, base, shot) {
  const page = await browser.newPage({ viewport: { width: shot.width, height: HEIGHT[shot.width] ?? 900 } });
  const problems = [];
  page.on('pageerror', (error) => problems.push(`page error: ${error.message}`));
  page.on('console', (message) => {
    const url = message.location().url ?? '';
    // Expected: a worst case's broken image points at a `.invalid` host (RFC 2606), and the API
    // client logs each failed read, which error states make on purpose (unmocked ones show in the bar).
    if (message.type() !== 'error' || /^https?:\/\/[^/]+\.invalid\//.test(url) || url.endsWith('/src/services/api.ts')) return;
    problems.push(`console error: ${message.text().split('\n')[0]} (${url})`);
  });
  try {
    await page.goto(`${base}${shot.url}`);
    await page.waitForSelector('html[data-frame-ready]', { timeout: READY_MS });
    if ((await page.getAttribute('html', 'data-frame-ready')) !== 'true') problems.push('the scenario setup failed');
    await page.evaluate(() => document.fonts.ready);
    const bar = page.locator('[aria-label="Frame requests"]');
    if (await bar.count()) {
      const lines = (await bar.innerText()).split('\n').filter((line) => /^(unmocked request|frame setup failed)/.test(line));
      problems.push(...lines);
    }
  } catch (error) {
    problems.push(`not ready: ${error.message.split('\n')[0]}`);
  }
  mkdirSync(dirname(join(out, shot.file)), { recursive: true });
  await page.screenshot({ path: join(out, shot.file), fullPage: true, animations: 'disabled' }).catch((error) => problems.push(`screenshot: ${error.message}`));
  await page.close();
  return problems;
}
