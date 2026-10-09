import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { cn } from '../../lib/utils';
import { buttonVariants } from './styles';

/**
 * The one "get out" affordance of a detail page: the same arrow, a lowercase
 * destination word ("feed", "tracks") and the same place above the title on
 * every page. `to` renders a router link; `onClick` a button (e.g. history back
 * with a fallback). Pull it left by its own padding so the arrow lines up with
 * the title's edge.
 */
export default function BackLink({
  label,
  to,
  onClick,
  className,
}: {
  /** The destination, lowercase: "feed", "tracks". */
  label: string;
  to?: string;
  onClick?: () => void;
  className?: string;
}) {
  const classes = cn(buttonVariants({ variant: 'ghost', size: 'sm' }), '-ml-2.5 mb-5 lowercase', className);
  const body = (
    <>
      <ArrowLeft aria-hidden="true" />
      {label}
    </>
  );
  if (to) {
    return (
      <Link to={to} onClick={onClick} className={classes} aria-label={`Back to ${label}`}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={classes} aria-label={`Back to ${label}`}>
      {body}
    </button>
  );
}
