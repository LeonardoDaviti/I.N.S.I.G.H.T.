// vitest setup for component tests (jsdom): jest-dom matchers and DOM cleanup.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { toast } from 'sonner';
import { afterAll, afterEach, vi } from 'vitest';

// sonner removes a closed toast 200 ms after it closes (its TIME_BEFORE_UNMOUNT), on a timer
// that unmounting the Toaster does not clear. A toast closed in a file's last test could fire
// that timer after vitest tore the file's jsdom down ("window is not defined", an unhandled
// error that fails the run), which happened on a loaded machine. A file that made toasts waits
// that long once at its end, so every such timer runs while the DOM still exists.
const SONNER_UNMOUNT_MS = 200;

afterEach(() => {
  cleanup();
});

afterAll(async () => {
  cleanup();
  // A timer set under fake timers never fires on its own; only real ones need the wait.
  if (vi.isFakeTimers()) vi.useRealTimers();
  if (toast.getHistory().length > 0) {
    await new Promise((resolve) => setTimeout(resolve, SONNER_UNMOUNT_MS + 50));
  }
});
