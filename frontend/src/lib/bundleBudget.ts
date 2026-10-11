/**
 * The reader's JS budget (Design Studio D8): the studio is a lazy chunk, and
 * the JS that opening `/` downloads may not grow more than 1% over the
 * committed baseline. Pure functions over Vite's build manifest, so the build
 * check (`scripts/bundle-check.mjs`) and its test share them.
 */

export interface ManifestChunk {
  file: string;
  isEntry?: boolean;
  isDynamicEntry?: boolean;
  imports?: string[];
  dynamicImports?: string[];
}

export type Manifest = Record<string, ManifestChunk>;

/** What `/` loads before the first paint: the app entry and the reader route. */
export const READER_ENTRIES = ['index.html', 'src/pages/ReaderPage.tsx'] as const;

/** The studio's own chunk: it must stay lazy. */
export const STUDIO_ENTRY = 'src/design/DesignStudio.tsx';

/** The growth the reader's initial JS may take over its baseline. */
export const BUDGET = 0.01;

/** The files the given entries load, following static imports only (lazy chunks wait). */
export function initialFiles(manifest: Manifest, entries: readonly string[]): string[] {
  const seen = new Set<string>();
  const files: string[] = [];
  const visit = (key: string) => {
    if (seen.has(key)) return;
    seen.add(key);
    const chunk = manifest[key];
    if (!chunk) return;
    files.push(chunk.file);
    for (const next of chunk.imports ?? []) visit(next);
  };
  for (const entry of entries) visit(entry);
  return files;
}

/** The reader's initial JS in bytes, given each file's size. */
export function readerBytes(manifest: Manifest, sizes: Record<string, number>): number {
  return initialFiles(manifest, READER_ENTRIES).reduce((sum, file) => sum + (sizes[file] ?? 0), 0);
}

/** Why the build breaks the budget; empty when it holds. */
export function budgetProblems({
  manifest,
  sizes,
  baselineBytes,
}: {
  manifest: Manifest;
  sizes: Record<string, number>;
  baselineBytes: number;
}): string[] {
  const problems: string[] = [];
  if (!manifest[STUDIO_ENTRY]?.isDynamicEntry) problems.push(`${STUDIO_ENTRY} is not a lazy chunk`);
  const initial = new Set(initialFiles(manifest, READER_ENTRIES));
  for (const [key, chunk] of Object.entries(manifest)) {
    if (key.startsWith('src/design/') && initial.has(chunk.file)) problems.push(`the reader's initial JS includes ${key}`);
  }
  const bytes = readerBytes(manifest, sizes);
  if (bytes > baselineBytes * (1 + BUDGET)) {
    const over = ((bytes / baselineBytes - 1) * 100).toFixed(2);
    problems.push(
      `the reader's initial JS is ${bytes} bytes, ${over}% over the baseline of ${baselineBytes} bytes (the budget is +${BUDGET * 100}%)`,
    );
  }
  return problems;
}
