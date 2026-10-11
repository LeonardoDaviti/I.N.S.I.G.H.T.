import { describe, expect, it } from 'vitest';

import { channelsToHex, documentedTokens, rootCustomProperties } from './liveStyle';

describe('reading the tokens live', () => {
  it('takes the token names and roles from the tokens doc\'s table, the contract', () => {
    const text = [
      '| Token | Role | Dark (default) | Light |',
      '| --- | --- | --- | --- |',
      '| `--bg` | page | `#121212` | `#ffffff` |',
      '| `--text-3` | tertiary: dates (≥ 4.5:1 on `--bg`) | `#808080` | `#6b6b6b` |',
      '',
      'Tailwind names: `bg-bg` and `--not-a-row`.',
    ].join('\n');
    expect(documentedTokens(text)).toEqual([
      { name: '--bg', role: 'page' },
      { name: '--text-3', role: 'tertiary: dates (≥ 4.5:1 on `--bg`)' },
    ]);
  });

  it('shows an RGB channel triplet as hex, and anything else as written', () => {
    expect(channelsToHex(' 18 18 18')).toBe('#121212');
    expect(channelsToHex('255 255 255')).toBe('#ffffff');
    expect(channelsToHex('0 0 0 / 0.6')).toBe('0 0 0 / 0.6');
    expect(channelsToHex('')).toBe('');
  });

  it('lists the custom properties the page\'s :root rules define, by prefix, once each', () => {
    const style = document.createElement('style');
    style.textContent = ':root { --dur-press: 120ms; --bg: 1 2 3 } :root.theme-light { --dur-press: 120ms; --dur-sheet: 260ms } .x { --dur-other: 1s }';
    document.head.append(style);
    expect(rootCustomProperties('--dur-')).toEqual(['--dur-press', '--dur-sheet']);
    style.remove();
  });
});
