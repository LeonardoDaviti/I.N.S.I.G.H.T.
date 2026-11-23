/**
 * Clipboard writes that survive a non-secure context. INSIGHT is served over plain HTTP on a LAN/Tailscale
 * address, where `navigator.clipboard` is undefined; deprecated document.execCommand('copy') is the only path
 * browsers still offer there, and it works inside a user gesture.
 */

export type ClipboardWriter = {
  clipboard?: { writeText?: (text: string) => Promise<void> };
};

/** Copy `text`, falling back to execCommand when the async API is unavailable. */
export async function writeToClipboard(
  text: string,
  navigatorRef: ClipboardWriter | undefined = typeof navigator === 'undefined' ? undefined : navigator,
  documentRef: Document | undefined = typeof document === 'undefined' ? undefined : document,
): Promise<void> {
  const writeText = navigatorRef?.clipboard?.writeText;
  if (writeText) {
    try {
      await writeText.call(navigatorRef!.clipboard, text);
      return;
    } catch {
      // Permission denied, or an API that refuses here: fall through to the recoverable path.
    }
  }

  if (!documentRef?.body) {
    throw new Error('Clipboard is unavailable in this context');
  }

  const area = documentRef.createElement('textarea');
  area.value = text;
  // readonly stops mobile keyboards popping up; the off-screen fixed position stops the
  // page scrolling to the element when we select it.
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '0';
  area.style.left = '0';
  area.style.width = '1px';
  area.style.height = '1px';
  area.style.opacity = '0';
  documentRef.body.appendChild(area);

  // Selecting our textarea blows away whatever the reader had highlighted, so put it back.
  const selection = documentRef.getSelection?.();
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

  let copied = false;
  try {
    area.select();
    area.setSelectionRange(0, text.length);
    copied = documentRef.execCommand('copy');
  } finally {
    documentRef.body.removeChild(area);
    if (selection && previousRange) {
      selection.removeAllRanges();
      selection.addRange(previousRange);
    }
  }

  if (!copied) {
    throw new Error('Clipboard is unavailable in this context');
  }
}
