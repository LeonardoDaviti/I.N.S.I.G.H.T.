import { forwardRef, type AnchorHTMLAttributes } from 'react';
import { Link, type LinkProps } from 'react-router-dom';
import { cn } from '../../lib/utils';

const LINK = 'text-link rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';

/**
 * An underlined link in the text colour (smol-style). Internal paths go through
 * the router; `external` opens a new tab with `rel="noreferrer"`.
 */
export const TextLink = forwardRef<HTMLAnchorElement, LinkProps & { muted?: boolean }>(function TextLink(
  { className, muted = false, ...props },
  ref,
) {
  return <Link ref={ref} className={cn(LINK, muted && 'text-fg-2', className)} {...props} />;
});

export const ExternalLink = forwardRef<HTMLAnchorElement, AnchorHTMLAttributes<HTMLAnchorElement>>(function ExternalLink(
  { className, ...props },
  ref,
) {
  return <a ref={ref} target="_blank" rel="noreferrer noopener" className={cn(LINK, className)} {...props} />;
});

export default TextLink;
