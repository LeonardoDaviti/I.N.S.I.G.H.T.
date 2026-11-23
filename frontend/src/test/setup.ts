// vitest setup for component tests (jsdom): jest-dom matchers and DOM cleanup.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { toast } from 'sonner';
import { afterAll, afterEach, vi } from 'vitest';

// sonner removes a closed toast 200 ms later on a timer unmounting does not clear; fired after vitest tore the
// jsdom down, it fails the run. A file that made toasts waits that long once at its end.
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
