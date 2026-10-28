import { beforeEach, describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { baseApi, renderPost, rssPost } from './PostDetailPage.testkit';
import { resetStoredChoices } from '../hooks/useShortcutPreference';
import { READING_KEYS } from '../hooks/useReadingSettings';
import { READING_TEXT_CLASS, SERIF_STACK } from '../lib/readingSettings';

// Reading settings (issue 0045): font, size and width, in the Aa popover, per device.

const STRUCTURED = rssPost({
  content_html: '<p>Opening line.</p><figure><img src="https://example.com/a.png" alt="A chart"><figcaption>The chart.</figcaption></figure>'
    + '<table><thead><tr><th>Metric</th></tr></thead><tbody><tr><td>42</td></tr></tbody></table><pre><code>print(1)</code></pre>',
});

function frame() {
  return document.querySelector<HTMLElement>('[data-reading-frame]')!;
}

async function openSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Reading settings' }));
  const popover = await screen.findByRole('dialog', { name: 'Reading settings' });
  await within(popover).findByRole('radiogroup', { name: 'Font' });
  return popover;
}

beforeEach(() => {
  window.localStorage.clear();
  resetStoredChoices();
});

describe('PostDetailPage reading settings', () => {
  it('by default sets nothing, so the post reads as before: 68ch, today\'s size, the sans', async () => {
    renderPost(baseApi(rssPost()));
    const article = await screen.findByRole('article', { name: 'Post content' });
    expect(frame()).not.toHaveAttribute('style');
    const text = article.firstElementChild as HTMLElement;
    expect(text.className).toBe(READING_TEXT_CLASS);
    expect(text.className).toContain('max-w-[var(--reading-measure,68ch)]');
    expect(text.className).toContain('text-[length:calc(1.0625rem*var(--reading-scale,1))]');
    expect(text.className).toContain('sm:text-[length:calc(1.125rem*var(--reading-scale,1))]');
    expect(text.className).toContain('leading-[1.7]');
    expect(screen.getByRole('button', { name: 'Reading settings' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('the Aa popover shows the three settings, today\'s checked', async () => {
    const user = userEvent.setup();
    renderPost(baseApi(rssPost()));
    const popover = await openSettings(user);
    expect(screen.getByRole('button', { name: 'Reading settings' })).toHaveAttribute('aria-expanded', 'true');
    const checked = (name: string) => within(within(popover).getByRole('radiogroup', { name })).getByRole('radio', { checked: true });
    expect(checked('Font')).toHaveTextContent('Sans');
    expect(checked('Size')).toHaveTextContent('100%');
    expect(checked('Width')).toHaveTextContent('Standard');
    expect(within(within(popover).getByRole('radiogroup', { name: 'Size' })).getAllByRole('radio').map((radio) => radio.textContent))
      .toEqual(['90%', '95%', '100%', '110%', '125%']);
  });

  it('each setting applies at once to the text behind and is kept on this device', async () => {
    const user = userEvent.setup();
    renderPost(baseApi(rssPost()));
    const popover = await openSettings(user);

    await user.click(within(popover).getByRole('radio', { name: 'Serif' }));
    expect(frame().style.getPropertyValue('--reading-font')).toBe(SERIF_STACK);
    expect(window.localStorage.getItem(READING_KEYS.font)).toBe('serif');

    await user.click(within(popover).getByRole('radio', { name: '125%' }));
    expect(frame().style.getPropertyValue('--reading-scale')).toBe('1.25');
    expect(window.localStorage.getItem(READING_KEYS.size)).toBe('5');

    await user.click(within(popover).getByRole('radio', { name: 'Wide' }));
    expect(frame().style.getPropertyValue('--reading-column')).toBe('52rem');
    expect(frame().style.getPropertyValue('--reading-measure')).toBe('84ch');
    expect(window.localStorage.getItem(READING_KEYS.width)).toBe('wide');

    // Back to today's choices: nothing is set again.
    await user.click(within(popover).getByRole('radio', { name: 'Sans' }));
    await user.click(within(popover).getByRole('radio', { name: '100%' }));
    await user.click(within(popover).getByRole('radio', { name: 'Standard' }));
    expect(frame().getAttribute('style') ?? '').toBe('');
  });

  it('a stored choice applies when the post opens; an unknown one is ignored', async () => {
    window.localStorage.setItem(READING_KEYS.font, 'serif');
    window.localStorage.setItem(READING_KEYS.size, '1');
    window.localStorage.setItem(READING_KEYS.width, 'enormous');
    renderPost(baseApi(rssPost()));
    await screen.findByRole('article', { name: 'Post content' });
    expect(frame().style.getPropertyValue('--reading-font')).toBe(SERIF_STACK);
    expect(frame().style.getPropertyValue('--reading-scale')).toBe('0.9');
    expect(frame().style.getPropertyValue('--reading-column')).toBe('');
  });

  it('applies to the title, and to the tables, figures, captions and code in the text', async () => {
    window.localStorage.setItem(READING_KEYS.size, '4');
    renderPost(baseApi(STRUCTURED));
    const article = await screen.findByRole('article', { name: 'Post content' });
    const text = article.firstElementChild as HTMLElement;
    for (const node of [article.querySelector('table'), article.querySelector('figcaption'), article.querySelector('pre')]) {
      expect(node).not.toBeNull();
      expect(text.contains(node)).toBe(true);
    }
    expect(screen.getByRole('heading', { level: 1 }).className).toContain('[font-family:var(--reading-font)]');
    // The interface around the text keeps its own type: the navigation does not read the variables.
    expect(screen.getByRole('navigation', { name: 'Post navigation' }).className).not.toContain('reading');
  });

  it('works from the keyboard: Enter opens, Tab and Space choose, Escape closes back to Aa without leaving the post', async () => {
    const user = userEvent.setup();
    renderPost(baseApi(rssPost()));
    const button = await screen.findByRole('button', { name: 'Reading settings' });
    button.focus();
    await user.keyboard('{Enter}');
    const popover = await screen.findByRole('dialog', { name: 'Reading settings' });
    await within(popover).findByRole('radiogroup', { name: 'Font' });
    expect(popover).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(within(popover).getByRole('radio', { name: 'Serif' })).toHaveFocus();
    await user.keyboard(' ');
    expect(window.localStorage.getItem(READING_KEYS.font)).toBe('serif');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Reading settings' })).toBeNull();
    expect(button).toHaveFocus();
    expect(screen.getByRole('article', { name: 'Post content' })).toBeInTheDocument();
  });

  it('a click outside closes the popover; the choice stays', async () => {
    const user = userEvent.setup();
    renderPost(baseApi(rssPost()));
    const popover = await openSettings(user);
    await user.click(within(popover).getByRole('radio', { name: 'Narrow' }));
    await user.click(screen.getByRole('heading', { level: 1 }));
    expect(screen.queryByRole('dialog', { name: 'Reading settings' })).toBeNull();
    expect(frame().style.getPropertyValue('--reading-column')).toBe('36rem');
  });
});
