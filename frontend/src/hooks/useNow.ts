import { useEffect, useState } from 'react';

/** Now, refreshed every `intervalMs` while the page is visible, so "fetched 3h ago" stays true. */
export function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') setNow(new Date());
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
