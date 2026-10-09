import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

const AnnounceContext = createContext<(message: string) => void>(() => {});

/**
 * The reader's one `aria-live="polite"` region (spec §F.6): read, star,
 * mark-through and undo results are announced here. Repeating the same message
 * alternates a trailing no-break space so screen readers announce it again.
 */
export function LiveRegionProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState('');
  const flip = useRef(false);
  const announce = useCallback((next: string) => {
    flip.current = !flip.current;
    setMessage(flip.current ? next : `${next} `);
  }, []);
  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div id="reader-live-region" aria-live="polite" aria-atomic="true" className="sr-only">
        {message}
      </div>
    </AnnounceContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export function useAnnounce() {
  return useContext(AnnounceContext);
}
