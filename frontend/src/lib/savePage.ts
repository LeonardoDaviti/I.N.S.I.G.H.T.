/**
 * Save any page: the save page's address and the bookmarklet that opens it. The bookmarklet only opens INSIGHT's
 * save page; nothing is saved until the owner presses Save there, so a website can never save into INSIGHT.
 */

export const SAVE_PATH = '/save';

/** The bookmarklet for an INSIGHT at `origin`: opens its save page for the current page in a new tab. */
export function bookmarkletCode(origin: string): string {
  const target = JSON.stringify(`${origin.replace(/\/+$/, '')}${SAVE_PATH}?url=`);
  return `javascript:(()=>{window.open(${target}+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title),'_blank','noopener')})()`;
}
