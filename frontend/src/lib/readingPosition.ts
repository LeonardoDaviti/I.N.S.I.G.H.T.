/** The share of a post read when worth showing (5% to 90%), else null. Apart from the hook, so a feed row doesn't load it. */
export function resumeShare(block?: number | null, blocks?: number | null): number | null {
  if (block == null || !blocks) return null;
  const share = block / blocks;
  return share >= 0.05 && share <= 0.9 ? share : null;
}
