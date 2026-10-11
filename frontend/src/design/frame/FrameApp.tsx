import { useState } from 'react';

import { bootFrame, type BootedFrame } from './boot';
import { parseFrameLocation } from './frameUrl';
import FrameRoot from './FrameRoot';

let booted: BootedFrame | null = null;
let walk = false;

/**
 * The chromeless frame route, `/design/frame/:page/:state?theme=&data=&walk=`, as the
 * whole document of an iframe. It boots once per window (StrictMode renders
 * twice): fixture `fetch`, in-memory storage, theme class; then the page renders.
 */
export default function FrameApp() {
  const [frame] = useState(() => {
    if (!booted) {
      const location = parseFrameLocation(window.location.pathname, window.location.search)
        ?? { page: '', state: '', theme: 'dark' as const, data: 'fixtures' as const };
      booted = bootFrame(window, location);
      walk = location.walk === true;
    }
    return booted;
  });
  return <FrameRoot booted={frame} walk={walk} />;
}
