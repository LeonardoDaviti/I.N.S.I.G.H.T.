/**
 * Clipboard writes that survive a non-secure context.
 *
 * navigator.clipboard is gated behind a *secure context*: HTTPS, or a localhost/127.0.0.1
 * origin. INSIGHT is served over plain HTTP on a LAN/Tailscale address, so on the deployed
 * instance `navigator.clipboard` is undefined entirely - reading `.writeText` off it throws
 * a TypeError. The copy button therefore worked in local dev (localhost IS a secure
 * context) and failed on the only machine anyone actually reads posts on.
 *
 * document.execCommand('copy') is deprecated, but it is the only clipboard path browsers
 * still offer over plain HTTP, and it works as long as it runs inside a user gesture.
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
      // Permission denied, or a browser that exposes the API but refuses it here.
      // Fall through rather than surfacing an error we can still recover from.
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
