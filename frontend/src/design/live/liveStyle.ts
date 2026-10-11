/**
 * Reading the design system from the running page (D3): the tokens come from
 * the CSS custom properties through getComputedStyle, so a specimen can't
 * drift from index.css.
 */
import { useSyncExternalStore } from 'react';

export interface DocumentedToken {
  name: string;
  role: string;
}

/** The tokens doc's table rows: `| \`--name\` | role | … |`. The doc is the contract (system/tokens.md). */
export function documentedTokens(text: string): DocumentedToken[] {
  return [...text.matchAll(/^\|\s*`(--[\w-]+)`\s*\|\s*(.*?)\s*\|/gm)].map((match) => ({ name: match[1], role: match[2] }));
}

/** `18 18 18` → `#121212`; any other value (an alpha, an empty string) as written. */
export function channelsToHex(value: string): string {
  const channels = value.trim().split(/\s+/);
  if (channels.length !== 3 || !channels.every((channel) => /^\d{1,3}$/.test(channel))) return value.trim();
  return `#${channels.map((channel) => Number(channel).toString(16).padStart(2, '0')).join('')}`;
}

/** A custom property's value on the root, as the page resolves it now. */
export function rootValue(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** The custom properties `:root` rules define with this prefix, in source order. */
export function rootCustomProperties(prefix: string): string[] {
  const names = new Set<string>();
  const visit = (rules: CSSRuleList) => {
    for (const rule of Array.from(rules)) {
      if ('cssRules' in rule && !(rule instanceof CSSStyleRule)) visit((rule as CSSGroupingRule).cssRules);
      if (!(rule instanceof CSSStyleRule) || !rule.selectorText.includes(':root')) continue;
      for (const property of Array.from(rule.style)) if (property.startsWith(prefix)) names.add(property);
    }
  };
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      visit(sheet.cssRules);
    } catch {
      // A cross-origin sheet can't be read; ours are same-origin.
    }
  }
  return [...names];
}

function subscribeToRootClass(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'style'] });
  return () => observer.disconnect();
}

/**
 * The root's class list, re-read when the theme flips, so live specimens
 * re-render with the other theme's values.
 */
export function useRootClass(): string {
  return useSyncExternalStore(subscribeToRootClass, () => document.documentElement.className);
}

function subscribeToReducedMotion(onChange: () => void): () => void {
  const query = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  query?.addEventListener?.('change', onChange);
  return () => query?.removeEventListener?.('change', onChange);
}

/** True when the reader asked for less motion. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribeToReducedMotion, () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);
}
