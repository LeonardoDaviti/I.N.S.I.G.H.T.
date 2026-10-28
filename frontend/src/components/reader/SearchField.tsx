import { useState } from 'react';
import { Search } from 'lucide-react';

import { fieldClass } from '../ui/styles';

/**
 * The search field (issue 0040): a `search` landmark whose Enter searches; empty searches
 * nothing. In the reader's toolbar it is compact and scoped to what is on screen; on the
 * search page it is the page's own field, holding the query.
 */
export default function SearchField({ label, initial = '', onSearch, autoFocus = false, className = '' }: {
  /** The accessible name, which says the scope ("Search Main feed"). */
  label: string;
  initial?: string;
  onSearch: (query: string) => void;
  autoFocus?: boolean;
  className?: string;
}) {
  const [value, setValue] = useState(initial);
  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        if (value.trim()) onSearch(value.trim());
      }}
      className={`relative min-w-0 ${className}`}
    >
      <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-3" />
      <input
        type="search"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        aria-label={label}
        placeholder="search"
        enterKeyHint="search"
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        className={`${fieldClass} h-9 pl-8 coarse:h-11`}
      />
    </form>
  );
}
