import { useState } from 'react';

import { bootFrame, type BootedFrame } from './boot';
import { parseFrameLocation } from './frameUrl';
import FrameRoot from './FrameRoot';
import { prototypeById, prototypeComponent } from '../prototypeRegistry';

let booted: BootedFrame | null = null;

/**
 * The chromeless frame route, `/design/frame/:page/:state?theme=&data=` (or
 * `/design/frame/prototype/:id/:state`), as the whole document of an iframe. It
 * boots once per window (StrictMode renders twice): fixture `fetch`, in-memory
 * storage, theme class; then the page renders. A prototype renders on the
 * fixtures of its README's page, for the state in the URL.
 */
export default function FrameApp() {
  const [frame] = useState(() => {
    if (!booted) {
      const location = parseFrameLocation(window.location.pathname, window.location.search)
        ?? { page: '', state: '', theme: 'dark' as const, data: 'fixtures' as const };
      const page = location.prototype ? prototypeById(location.prototype)?.page ?? '' : location.page;
      booted = bootFrame(window, { ...location, page });
    }
    return booted;
  });
  return <FrameRoot booted={frame} prototype={frame.location.prototype ? prototypeComponent(frame.location.prototype) : undefined} />;
}
