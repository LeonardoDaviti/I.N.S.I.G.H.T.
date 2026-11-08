import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import SuggestedVoices from './SuggestedVoices';
import VoiceHeader from './VoiceHeader';
import VoicesPanel from './VoicesPanel';
import AlsoOn from '../reader/AlsoOn';
import { makeFakeApi } from '../../test/fakeApi';
import { renderWithProviders } from '../../test/render';
import type { Voice, VoiceSuggestions } from '../../services/api';
import { voicesApi } from '../../services/voices';

// Issue 0132 A: suggested voices with their evidence, the owner's Join / Not the same / Related, a voice's channel
// tabs, "Also on <channel>". Every name is invented.

const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-8222-222222222222';
const C = '33333333-3333-4333-8333-333333333333';

const source = (id: string, name: string, kind = 'site', posts = 12) => ({ id, name, kind, posts, enabled: true, voice_id: null });

const suggestions = (over: Partial<VoiceSuggestions> = {}): VoiceSuggestions => ({
  success: true, computed_at: '2026-11-08T08:00:00Z', computing: false,
  voices: [{
    key: `${A}|${B}`, sources: [source(A, 'Quillon Desk'), source(B, '@quillon', 'youtube', 30)], voice_ids: [], same_channel: false,
    edges: [{ a: A, b: B, verdict: 'join', evidence: [
      { rule: 'standing_link', line: "@quillon links Quillon Desk in 28/30 own posts", posts: ['p-1', 'p-2'] },
      { rule: 'shared_name', line: 'shared name quillon', posts: [] },
    ] }],
  }],
  possible: [{ a: source(A, 'Quillon Desk'), b: source(C, 'Quillon Notes'), names: ['quillon'], evidence: [{ rule: 'shared_name', line: 'shared name quillon', posts: [] }] }],
  related: [],
  ...over,
});

const voice = (over: Partial<Voice> = {}): Voice => ({
  id: 'v-1', name: 'Quillon Desk', kind: null, entity_id: null, created_at: '2026-11-08T08:00:00Z', confirmed_at: '2026-11-08T08:00:00Z',
  channels: [
    { id: A, name: 'Quillon Desk', platform: 'rss', kind: 'site', enabled: true, in_main_digest: true, priority: 999, posts: 40, last_post_at: null },
    { id: B, name: '@quillon', platform: 'youtube', kind: 'youtube', enabled: true, in_main_digest: false, priority: 999, posts: 30, last_post_at: null },
  ],
  related: [], in_main_digest: true, priority: 999, ...over,
});

afterEach(() => vi.restoreAllMocks());

describe('Suggested voices', () => {
  it('shows each suggestion with its evidence and joins it only when asked', async () => {
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(suggestions());
    const join = vi.spyOn(voicesApi, 'join').mockResolvedValue({ success: true, voice: voice(), queued_sources: [A, B] });
    renderWithProviders(<SuggestedVoices />, { api: makeFakeApi({}) });
    expect(await screen.findByText("@quillon links Quillon Desk in 28/30 own posts")).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /^post \d$/ })).toHaveLength(2);
    expect(join).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByTestId('voice-suggestion')).getByRole('button', { name: 'Join' }));
    await waitFor(() => expect(join).toHaveBeenCalledWith([A, B], expect.objectContaining({ evidence: expect.any(Array) })));
  });

  it('Not the same keeps a pair apart; a name alone is only "possible"', async () => {
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(suggestions());
    const notSame = vi.spyOn(voicesApi, 'notSame').mockResolvedValue({ success: true });
    renderWithProviders(<SuggestedVoices />, { api: makeFakeApi({}) });
    const possible = await screen.findByRole('region', { name: 'Possible' });
    expect(possible).toHaveTextContent('A shared name and nothing else: never suggested');
    fireEvent.click(screen.getAllByRole('button', { name: 'Not the same' })[0]);
    await waitFor(() => expect(notSame).toHaveBeenCalledWith(A, B, expect.any(Array)));
  });

  it('says the same channel added twice, and related voices need a bio', async () => {
    const twice = suggestions();
    twice.voices[0].same_channel = true;
    twice.related = [{ a: source(A, 'Orbit Newsroom'), b: source(C, 'zed_q', 'x'), evidence: [{ rule: 'official_and_focused', line: "zed_q: 55% of 20 read posts about 'orbit', the other's own maker (needs a bio)", posts: [] }] }];
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(twice);
    const related = vi.spyOn(voicesApi, 'related').mockResolvedValue({ success: true, voices: [] });
    renderWithProviders(<SuggestedVoices />, { api: makeFakeApi({}) });
    expect(await screen.findByText('The same channel twice: disable one?')).toBeInTheDocument();
    expect(screen.getByText(/the other's own maker \(needs a bio\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Related' }));
    await waitFor(() => expect(related).toHaveBeenCalledWith(A, C, expect.any(Array)));
  });

  it('nothing suggested, and while it looks', async () => {
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(suggestions({ voices: [], possible: [], computing: true, computed_at: null }));
    renderWithProviders(<SuggestedVoices />, { api: makeFakeApi({}) });
    expect(await screen.findByText('Looking at your sources')).toBeInTheDocument();
  });
});

describe('Your voices', () => {
  it('lists voices of 2+ channels; removing one keeps its channels', async () => {
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(suggestions({ voices: [], possible: [] }));
    vi.spyOn(voicesApi, 'list').mockResolvedValue({ success: true, voices: [voice(), voice({ id: 'v-2', name: 'Lone', channels: [voice().channels[0]] })] });
    const remove = vi.spyOn(voicesApi, 'remove').mockResolvedValue({ success: true, source_ids: [A, B] });
    renderWithProviders(<VoicesPanel />, { api: makeFakeApi({}) });
    expect(await screen.findAllByTestId('voice-row')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Remove voice' }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith('v-1'));
  });
});

describe('a voice page', () => {
  it('has a tab for every channel together and one per channel, keeping the view', () => {
    renderWithProviders(<VoiceHeader scope="voice:v-1" voice={voice()} />, { api: makeFakeApi({}), route: '/read/voice/v-1?view=news' });
    const tabs = screen.getByRole('navigation', { name: 'Channels' });
    const links = Array.from(tabs.querySelectorAll('a'));
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/read/voice/v-1?view=news', `/read/source/${A}?view=news`, `/read/source/${B}?view=news`]);
    expect(links[0]).toHaveAttribute('aria-current', 'page');
    expect(screen.getByText(/One voice, 2 channels/)).toBeInTheDocument();
  });

  it('a channel read alone names its voice and renames nothing', () => {
    renderWithProviders(<VoiceHeader scope={`source:${B}`} voice={voice()} />, { api: makeFakeApi({}), route: `/read/source/${B}` });
    expect(screen.getByText('A channel of')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rename' })).not.toBeInTheDocument();
    const current = screen.getByRole('navigation', { name: 'Channels' }).querySelector('[aria-current="page"]');
    expect(current?.getAttribute('href')).toBe(`/read/source/${B}`);
  });

  it('renames the voice (its main channel\'s name until you do)', async () => {
    const rename = vi.spyOn(voicesApi, 'rename').mockResolvedValue({ success: true, voice: voice({ name: 'Quillon' }) });
    renderWithProviders(<VoiceHeader scope="voice:v-1" voice={voice()} />, { api: makeFakeApi({}) });
    fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
    fireEvent.change(screen.getByLabelText('Voice name'), { target: { value: 'Quillon' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(rename).toHaveBeenCalledWith('v-1', 'Quillon'));
  });
});

describe('0132 C2: other channels not followed, and channel profiles', () => {
  const tg = {
    key: 'tg:quillonnews', url: 'https://t.me/quillonnews', label: 'quillonnews', platform: 'Telegram', of: ['Quillon Desk'],
    why: [{ rule: 'profile' as const, line: 'its profile links it (linked account)', posts: [] }],
  };

  it('lists them under Suggested voices; Add opens the Add-source flow on the address, never adds alone', async () => {
    vi.spyOn(voicesApi, 'suggestions').mockResolvedValue(suggestions({
      not_followed: [{ subject: { kind: 'source', id: A, name: 'Quillon Desk' }, channels: [tg] }], profiles: 3,
    }));
    vi.spyOn(voicesApi, 'profilesSetting').mockResolvedValue({ success: true, on: true });
    const off = vi.spyOn(voicesApi, 'setProfilesSetting').mockResolvedValue({ success: true, on: false });
    const onFollow = vi.fn();
    renderWithProviders(<SuggestedVoices onFollow={onFollow} />, { api: makeFakeApi({}) });
    const row = await screen.findByTestId('not-followed');
    expect(row).toHaveTextContent('Not followed: quillonnews · Telegram — Add');
    expect(row).toHaveTextContent('its profile links it (linked account)');
    expect(onFollow).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByRole('button', { name: 'Add' }));
    expect(onFollow).toHaveBeenCalledWith('https://t.me/quillonnews');
    expect(await screen.findByTestId('profiles-switch')).toHaveTextContent('read monthly · 3 profiles read');
    fireEvent.click(screen.getByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(off).toHaveBeenCalledWith(false));
  });

  it('the voice page lists them with Add to the feed finder', async () => {
    vi.spyOn(voicesApi, 'get').mockResolvedValue({ success: true, voice: voice(), not_followed: [tg] });
    renderWithProviders(<VoiceHeader scope="voice:v-1" voice={voice()} />, { api: makeFakeApi({}), route: '/read/voice/v-1' });
    const row = await screen.findByTestId('not-followed');
    expect(within(row).getByRole('link', { name: 'Add' })).toHaveAttribute('href', `/sources?follow=${encodeURIComponent('https://t.me/quillonnews')}`);
  });
});

describe('Also on', () => {
  it('one line per other channel, a link to that post', () => {
    renderWithProviders(<AlsoOn lines={[{ id: 'p-9', source_id: B, source_display_name: '@quillon', platform: 'youtube', title: 'A talk',
      url: null, sort_at: '2026-11-08T09:00:00Z', why: 'links' }]} now={new Date('2026-11-08T12:00:00Z')} />, { api: makeFakeApi({}) });
    expect(screen.getByRole('link', { name: 'Also on @quillon' })).toHaveAttribute('href', '/posts/p-9');
  });
});
