import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { CornerDownLeft } from 'lucide-react';
import { Dialog, DialogContent } from '../ui/Dialog';
import Kbd from '../ui/Kbd';
import { useTheme } from '../ThemeProvider';
import { cn } from '../../lib/utils';
import { destinations, filterDestinations, insideDesignFrame, type Destination } from './navigation';
import { searchHref } from '../../lib/search';
import { useFolders } from '../../hooks/useReaderDirectory';

type Option = Destination | { id: 'toggle-theme' | 'reading-settings'; label: string; group: string; to?: undefined };

/**
 * The quick switcher: the places to go, then "Search posts…", which searches every post
 * for what was typed (issue 0040). It opens
 * many times a day, so it never animates (emil: frequency decides motion).
 * Combobox + listbox semantics; ↑/↓ move, Enter goes, Esc closes.
 */
export default function QuickSwitcher({ open, onOpenChange, onOpenReadingSettings }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Opens the reading settings (font, size, width; issue 0045). */
  onOpenReadingSettings?: () => void;
}) {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);
  const folders = useFolders();
  const items = useMemo(() => destinations(folders.data ?? [], { studio: !insideDesignFrame() }), [folders.data]);

  const options: Option[] = useMemo(() => {
    const themeOption: Option = {
      id: 'toggle-theme',
      label: theme === 'theme-dark' ? 'Switch to light theme' : 'Switch to dark theme',
      group: 'theme',
    };
    const matches: Option[] = filterDestinations(query, items);
    const themeWords = 'theme dark light mode appearance';
    const q = query.trim().toLowerCase();
    if (!q || q.split(/\s+/).every((word) => `${themeOption.label.toLowerCase()} ${themeWords}`.includes(word))) {
      matches.push(themeOption);
    }
    const readingWords = 'reading settings font size width text serif sans aa';
    if (onOpenReadingSettings && (!q || q.split(/\s+/).every((word) => readingWords.includes(word)))) {
      matches.push({ id: 'reading-settings', label: 'Reading settings: font, size, width', group: 'settings' });
    }
    // Always last, so a typed place still comes first; with nothing else matching it is the one option.
    const typed = query.trim();
    matches.push({
      id: 'search-posts',
      label: typed ? `Search posts for “${typed}”` : 'Search posts…',
      group: 'search',
      to: searchHref({ q: typed }),
    });
    return matches;
  }, [query, theme, items, onOpenReadingSettings]);

  useEffect(() => {
    if (!open) {
      setQuery('');
      setActive(0);
    }
  }, [open]);

  useEffect(() => {
    setActive(0);
  }, [query]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const choose = (option: Option | undefined) => {
    if (!option) return;
    onOpenChange(false);
    if (option.id === 'toggle-theme') toggleTheme();
    else if (option.id === 'reading-settings') onOpenReadingSettings?.();
    else if (option.to) navigate(option.to);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((index) => (options.length ? (index + 1) % options.length : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => (options.length ? (index - 1 + options.length) % options.length : 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      choose(options[active]);
    }
  };

  const optionId = (index: number) => `${listId}-option-${index}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Go to"
        hideTitle
        instant
        showClose={false}
        className="top-[18vh] w-[min(34rem,calc(100vw-2rem))] translate-y-0 p-0"
      >
        <div className="flex items-center gap-2 border-b border-line px-4">
          <input
            autoFocus
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={options.length ? optionId(active) : undefined}
            aria-autocomplete="list"
            aria-label="Go to"
            placeholder="Go to…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            className="min-h-[3rem] w-full min-w-0 border-0 bg-transparent text-[0.9375rem] text-fg placeholder:text-fg-3 focus:outline-none focus-visible:outline-none"
          />
          <Kbd>esc</Kbd>
        </div>
        <ul ref={listRef} id={listId} role="listbox" aria-label="Destinations" className="max-h-[min(22rem,60dvh)] overflow-y-auto p-1.5">
          {options.map((option, index) => (
            <li
              key={option.id}
              id={optionId(index)}
              data-index={index}
              role="option"
              aria-selected={index === active}
              onMouseMove={() => setActive(index)}
              onClick={() => choose(option)}
              className={cn(
                'flex min-h-[2.5rem] cursor-pointer items-center gap-3 rounded-md px-3 text-[0.875rem]',
                index === active ? 'bg-inverse text-inverse-fg' : 'text-fg',
              )}
            >
              <span className="min-w-0 flex-1 truncate">{option.label}</span>
              <span className={cn('shrink-0 text-[0.75rem] lowercase', index === active ? 'text-inverse-fg/70' : 'text-fg-3')}>
                {option.group}
              </span>
              {index === active ? <CornerDownLeft aria-hidden="true" className="h-3.5 w-3.5 shrink-0" /> : null}
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

