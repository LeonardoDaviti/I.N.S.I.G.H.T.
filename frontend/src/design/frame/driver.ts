/**
 * What a scenario may do once its page has rendered, to reach a state no URL
 * can (⌘K open, rows selected): find, click and press, in the frame's document.
 * Each step waits for its element, so it runs after the page's data arrives.
 */
export interface FrameDriver {
  /** The first element matching `selector` (and `text`, when given), once it exists. */
  find(selector: string, text?: RegExp): Promise<HTMLElement>;
  click(selector: string, text?: RegExp): Promise<void>;
  /** A keydown on the document (or the element matching `selector`). */
  press(key: KeyboardEventInit & { key: string }, selector?: string): Promise<void>;
}

const STEP_TIMEOUT_MS = 5_000;

export function createFrameDriver(doc: Document, timeoutMs = STEP_TIMEOUT_MS): FrameDriver {
  const query = (selector: string, text?: RegExp) => [...doc.querySelectorAll<HTMLElement>(selector)]
    .find((element) => !text || text.test(element.textContent ?? '') || text.test(element.getAttribute('aria-label') ?? ''));

  const find = (selector: string, text?: RegExp) => new Promise<HTMLElement>((resolve, reject) => {
    const started = Date.now();
    const look = () => {
      const element = query(selector, text);
      if (element) resolve(element);
      else if (Date.now() - started > timeoutMs) reject(new Error(`frame: no ${selector}${text ? ` matching ${text}` : ''}`));
      else setTimeout(look, 30);
    };
    look();
  });

  return {
    find,
    async click(selector, text) {
      (await find(selector, text)).click();
    },
    async press(key, selector) {
      const target = selector ? await find(selector) : doc.body;
      target.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...key }));
    },
  };
}
