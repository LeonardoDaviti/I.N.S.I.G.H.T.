/**
 * Save any page (issue 0031): the save page's address and the bookmarklet that opens it.
 *
 * The bookmarklet only opens INSIGHT's own save page in a new tab, with the page's address
 * and title; nothing is saved until the owner presses Save there (a POST from INSIGHT's
 * page), so a website can never save into INSIGHT by itself.
 */

export const SAVE_PATH = '/save';

/** The bookmarklet for an INSIGHT at `origin`: opens its save page for the current page in a new tab. */
export function bookmarkletCode(origin: string): string {
  const target = JSON.stringify(`${origin.replace(/\/+$/, '')}${SAVE_PATH}?url=`);
  return `javascript:(()=>{window.open(${target}+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title),'_blank','noopener')})()`;
}
