/**
 * The share of a post read, when worth showing (issue 0030): started (5%) and not
 * nearly done (90%); otherwise null. The post's offer and its feed row use the same.
 * Pure, and apart from the post page's hook, so a feed row does not load the hook.
 */
export function resumeShare(block?: number | null, blocks?: number | null): number | null {
  if (block == null || !blocks) return null;
  const share = block / blocks;
  return share >= 0.05 && share <= 0.9 ? share : null;
}
