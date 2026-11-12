// Discover's "main source missing" lines (issue 0170): what each row says, from the server's row. Pure.
import type { MainSourceEvent, MainSourceRow, MainSourceTest } from '../services/api';
import { formatCount, plural } from './format.ts';
import { FOLLOW_LABELS } from './discover.ts';

/** "posts on X", "its Telegram channel", "its /blog/ section", "its site": where the actor's own posts are. */
export function channelPlace(row: MainSourceRow): string {
  const { channel } = row;
  if (channel.kind === 'account') return channel.platform === 'x' ? 'its posts on X' : 'its Telegram channel';
  if (channel.kind === 'source') return 'its own source';
  return channel.prefix && channel.prefix !== '/' ? `its ${channel.prefix} section` : 'its site';
}

/** The row's heading: the channel to follow, or the followed source it is about. */
export function rowTitle(row: MainSourceRow): string {
  if (row.kind === 'disabled' && row.source) return `${row.source.name} is turned off`;
  return row.channel.key;
}

/** Why the row is here, in one sentence. */
export function rowReason(row: MainSourceRow): string {
  const n = row.events.length;
  const events = plural(n, 'event');
  const actor = row.actor.name || 'The actor';
  if (row.kind === 'wrong_section' && row.source) {
    const watching = row.source.watch ? ` (it watches ${row.source.watch})` : '';
    return `You follow ${row.source.name}${watching}, but ${actor}'s own page for ${events} is under ${row.channel.prefix ?? '/'}: `
      + 'follow this section too.';
  }
  if (row.kind === 'disabled') {
    return `${actor}'s own source for ${events} your sources covered; it is turned off, so none of them came from ${actor}.`;
  }
  return `${events} your sources covered ${n === 1 ? 'links' : 'link'} ${actor}'s own post in ${channelPlace(row)}, which you don't follow.`;
}

/** What the follow test found, or that it hasn't run yet. */
export function testLine(test: MainSourceTest | null | undefined): string {
  if (!test) return 'Not tested yet: opening Discover tests it in the background.';
  const held = typeof test.holds === 'number' && test.of ? ` (holds ${formatCount(test.holds)} of ${plural(test.of, 'event page')})` : '';
  if (test.label === 'feed') return `${FOLLOW_LABELS.feed}${held}`;
  if (test.label === 'page') {
    const offer = test.pages?.[0];
    const found = offer?.found ?? test.preview?.found;
    const prefix = offer?.prefix ?? test.preview?.prefix;
    const what = typeof found === 'number' ? `: reads ${plural(found, 'article')}${prefix ? ` under ${prefix}` : ''}` : '';
    return `${FOLLOW_LABELS.page}${what}${held}`;
  }
  if (test.label === 'headlines') return 'No feed, and page watching reads none of its pages';
  return FOLLOW_LABELS[test.label] ?? test.label;
}

/** How the event carries the actor's own page. */
export function ownPageLine(own: MainSourceEvent['own_page']): string {
  if (!own) return '';
  if (own.how === 'held') return own.held_by.length ? `held as a post of ${own.held_by.join(', ')}` : 'held under another source';
  if (own.how === 'main_link') return 'the page a link post carries';
  if (own.how === 'source_page') return 'the page your sources link';
  return 'linked by your sources';
}

/** "model release" from "model_release". */
export function eventTypeLabel(type: string): string {
  return type.replace(/_/g, ' ');
}

/** The button that follows the row's channel through Add source; none for a turned-off source. */
export function followLabel(row: MainSourceRow): string | null {
  if (row.kind === 'disabled') return null;
  return row.kind === 'wrong_section' ? 'Follow this section…' : 'Follow…';
}
