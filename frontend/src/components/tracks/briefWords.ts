// 0245 (frontend v10.28): the track briefer's words and the pure parts of its views: days, weeks, a thing's name and
// facts, the cite numbers, the filter chips a kind's typed fields give, and sorting. Nothing here names a track, a
// kind or a field: every rule is about a type (text, number, money, link, enum).
import type { BriefPoint, Thing, ThingFieldDef, ThingSection, ThingValue } from '../../services/tracks';

const DAY = 86_400_000;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const parse = (iso: string) => (/^\d{4}-\d{2}-\d{2}$/.test(iso) ? Date.parse(`${iso}T00:00:00Z`) : Date.parse(iso));

/** A day as the brief says it: its weekday within the last 6 days ("Tue"), else "13 Nov" (the year when not this one). */
export function dayWord(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return '';
  const t = parse(iso);
  if (Number.isNaN(t)) return '';
  const d = new Date(t);
  if (now.getTime() - t < 6 * DAY && now.getTime() >= t) return WEEKDAYS[d.getDay()];
  const base = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return d.getFullYear() === now.getFullYear() ? base : `${base} ${d.getFullYear()}`;
}

/** A Monday (YYYY-MM-DD, UTC as the backend's weeks) as the strip shows it: "16 Nov". */
export function weekDay(iso: string): string {
  const d = new Date(parse(iso));
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

/** "week of 16-22 Nov" (or "week of 28 Sep-4 Oct" across months). */
export function weekLine(start: string, end: string): string {
  const a = new Date(parse(start));
  const b = new Date(parse(end));
  return a.getUTCMonth() === b.getUTCMonth()
    ? `week of ${a.getUTCDate()}-${b.getUTCDate()} ${MONTHS[b.getUTCMonth()]}`
    : `week of ${weekDay(start)}-${weekDay(end)}`;
}

/** The Monday (UTC) of the week a time falls in, at 00:00 (ISO): the quick look's start when the track was never opened. */
export function mondayOf(now: Date = new Date()): string {
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString();
}

/** The quick look's head: "since Tue · 6 new" (things and the posts that gave none). */
export function sinceLine(since: string, n: number, now: Date = new Date()): string {
  return `since ${dayWord(since, now)} · ${n} new`;
}

/** The rail's count: "3 new things", "9+ new things"; null at 0 (silent). */
export function railThings(n: number | undefined): string | null {
  if (!n || n < 1) return null;
  return `${n > 9 ? '9+' : n} new ${n === 1 ? 'thing' : 'things'}`;
}

/** A kind as a heading when the backend gave none: "print_test" → "Print test". */
export function kindWord(kind: string): string {
  const s = kind.replace(/_/g, ' ');
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const fieldWord = kindWord;

/** A thing's name: its first field (the schema's name field), else its first filled one. */
export function thingName(thing: Thing, fields: ThingFieldDef[]): string {
  const first = fields[0] && thing.fields[fields[0].name];
  if (first) return first.shown;
  const any = Object.values(thing.fields)[0];
  return any ? any.shown : '(unnamed)';
}

/** The facts after the name: up to `max` filled non-link fields, as shown ("PETG · 4 hours"). */
export function thingFacts(thing: Thing, fields: ThingFieldDef[], max = 3): string[] {
  return fields.slice(1).filter((f) => f.type !== 'link' && thing.fields[f.name]).slice(0, max)
    .map((f) => thing.fields[f.name].shown);
}

/** The thing's link fields (an external link a post gave), in schema order. */
export function thingLinks(thing: Thing, fields: ThingFieldDef[]): Array<{ name: string; url: string }> {
  return fields.filter((f) => f.type === 'link' && typeof thing.fields[f.name]?.value === 'string')
    .map((f) => ({ name: f.name, url: thing.fields[f.name].value as string }));
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/**
 * The superscripts of a set of points: each cited thing found in the sections gets a number (its row number when the
 * backend gave one, else in the order first cited) and the post it links to (its newest report). A cite whose thing
 * is not on the page is left out.
 */
export function citeMarks(points: BriefPoint[], sections: ThingSection[]): Map<string, { n: number; thing: Thing }> {
  const things = new Map(sections.flatMap((s) => s.things.map((t) => [t.id, t] as const)));
  const out = new Map<string, { n: number; thing: Thing }>();
  let next = 1;
  const used = new Set<number>();
  for (const p of points) for (const c of p.cites) if (c.n != null) used.add(c.n);
  for (const p of points) {
    for (const c of p.cites) {
      const thing = things.get(c.thing);
      if (!thing || out.has(c.thing) || !thing.posts.length) continue;
      let n = c.n;
      if (n == null) {
        while (used.has(next)) next += 1;
        n = next;
        used.add(n);
      }
      out.set(c.thing, { n, thing });
    }
  }
  return out;
}

/** The newest post a list shows (ISO), to tell whether the points are older than it. */
export function newestAt(times: Array<string | null | undefined>): number {
  return times.reduce<number>((m, t) => Math.max(m, t ? Date.parse(t) || 0 : 0), 0);
}

// ---- the tables: filter chips and sorting ------------------------------------------------------------------------

export interface FilterChipDef {
  /** Its group (the field): chips of one group replace each other, except enum values, which add up. */
  field: string;
  label: string;
  /** The API's params it sets (`<field>.min`, `<field>.max`, `<field>.currency`, `<field>=a,b`, `<field>=any`). */
  params: Record<string, string>;
  /** An enum value (several of one field are OR-ed into one param). */
  value?: string;
}

const numberOf = (v: ThingValue | undefined) => (v && typeof v === 'object' && typeof v.number === 'number' ? v : null);

/** A round number near x (2 significant digits): the chips' edges read as people say them ("1,500", "30"). */
export function niceNumber(x: number): number {
  if (x === 0) return 0;
  const p = 10 ** (Math.floor(Math.log10(Math.abs(x))) - 1);
  return Math.round(x / p) * p;
}

const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 });

/**
 * The chips a kind's typed fields give over its rows: a number or money field with two or more different values
 * splits at a round middle ("≤ 1,500 USD", "≥ 1,500 USD"; money only in its most common currency); an enum, one chip
 * per value its rows hold; a link, "has <field>". Text fields give none (a question box is later, 0098).
 */
export function filterChips(fields: ThingFieldDef[], things: Thing[]): FilterChipDef[] {
  const out: FilterChipDef[] = [];
  for (const f of fields.slice(1)) {
    const vals = things.map((t) => t.fields[f.name]?.value);
    if (f.type === 'number' || f.type === 'money') {
      let nums = vals.map(numberOf).filter((v): v is NonNullable<ReturnType<typeof numberOf>> => v !== null);
      let tail = f.type === 'number' ? (f.unit || nums.find((v) => v.unit)?.unit || '') : '';
      const params: Record<string, string> = {};
      if (f.type === 'money') {
        const by = new Map<string, number>();
        for (const v of nums) if (v.currency) by.set(v.currency, (by.get(v.currency) ?? 0) + 1);
        const top = [...by.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0];
        if (!top) continue;
        nums = nums.filter((v) => v.currency === top);
        tail = top;
        params[`${f.name}.currency`] = top;
      }
      const distinct = [...new Set(nums.map((v) => v.number))].sort((a, b) => a - b);
      if (distinct.length < 2) continue;
      const mid = niceNumber(distinct[Math.floor((distinct.length - 1) / 2)]);
      const say = (n: number) => `${fmt(n)}${tail ? ` ${tail}` : ''}`;
      out.push({ field: f.name, label: `${fieldWord(f.name)} ≤ ${say(mid)}`, params: { ...params, [`${f.name}.max`]: String(mid) } });
      out.push({ field: f.name, label: `${fieldWord(f.name)} ≥ ${say(mid)}`, params: { ...params, [`${f.name}.min`]: String(mid) } });
    } else if (f.type === 'enum') {
      const held = new Set(vals.filter((v): v is string => typeof v === 'string'));
      const order = f.values?.length ? f.values.filter((v) => held.has(v)) : [...held].sort();
      for (const v of order) out.push({ field: f.name, label: v, params: { [f.name]: v }, value: v });
    } else if (f.type === 'link') {
      if (vals.some((v) => typeof v === 'string')) out.push({ field: f.name, label: `has ${fieldWord(f.name).toLowerCase()}`, params: { [f.name]: 'any' } });
    }
  }
  return out;
}

/** The chosen chips as the API's params (enum values of one field joined with commas). */
export function chipParams(chosen: FilterChipDef[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const c of chosen) {
    if (c.value !== undefined) {
      out[c.field] = out[c.field] ? `${out[c.field]},${c.value}` : c.value;
    } else Object.assign(out, c.params);
  }
  return out;
}

/** Toggle a chip: an enum value adds or leaves; any other chip replaces its field's other chip. */
export function toggleChip(chosen: FilterChipDef[], chip: FilterChipDef): FilterChipDef[] {
  const same = (c: FilterChipDef) => c.field === chip.field && c.label === chip.label;
  if (chosen.some(same)) return chosen.filter((c) => !same(c));
  if (chip.value !== undefined) return [...chosen, chip];
  return [...chosen.filter((c) => c.field !== chip.field || c.value !== undefined), chip];
}

export type SortState = { field: string; dir: 'asc' | 'desc' } | null;

/** Rows sorted by a field (numbers by their number, the rest as words; empty last); null: as given (newest first). */
export function sortThings(things: Thing[], sort: SortState): Thing[] {
  if (!sort) return things;
  const key = (t: Thing) => {
    const v = t.fields[sort.field]?.value;
    const n = numberOf(v);
    return n ? n.number : typeof v === 'string' ? v.toLowerCase() : null;
  };
  return [...things].sort((a, b) => {
    const x = key(a);
    const y = key(b);
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return sort.dir === 'asc' ? c : -c;
  });
}

/** The next sort a header click gives: ascending, descending, then back to newest first. */
export function nextSort(sort: SortState, field: string): SortState {
  if (!sort || sort.field !== field) return { field, dir: 'asc' };
  return sort.dir === 'asc' ? { field, dir: 'desc' } : null;
}

// ---- the schema editor ---------------------------------------------------------------------------------------------

export const FIELD_NAME = /^[a-z][a-z0-9_]{0,39}$/;

/** A name as typed ("Print time") as the schema keeps it ("print_time"). */
export function fieldKey(typed: string): string {
  return typed.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 40);
}

/** The track's kinds and fields query (the page and the sheet's editor share it). */
export const schemaKey = (id: string) => ['markx-track-schema', id] as const;
