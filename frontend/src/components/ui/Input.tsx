import { forwardRef, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '../../lib/utils';
import { fieldClass } from './styles';

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, type = 'text', ...props },
  ref,
) {
  return <input ref={ref} type={type} className={cn(fieldClass, 'min-h-[2.25rem] coarse:min-h-[2.75rem]', className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...props },
  ref,
) {
  return <textarea ref={ref} className={cn(fieldClass, 'min-h-[5rem] py-2 leading-[1.55]', className)} {...props} />;
});

/** A native select (keyboard, mobile pickers and a11y for free), restyled. */
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select(
  { className, children, ...props },
  ref,
) {
  return (
    <span className={cn('relative inline-flex min-w-0', className)}>
      <select
        ref={ref}
        className={cn(fieldClass, 'min-h-[2.25rem] appearance-none pr-8 coarse:min-h-[2.75rem]')}
        {...props}
      >
        {children}
      </select>
      <ChevronDown aria-hidden="true" className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-3" />
    </span>
  );
});

/** A visible label above a field, with an optional hint line. */
export function Field({
  label,
  hint,
  htmlFor,
  children,
  className,
}: {
  label: string;
  hint?: string;
  htmlFor: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={htmlFor} className="block text-[0.8125rem] font-medium text-fg">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[0.75rem] text-fg-3">{hint}</p> : null}
    </div>
  );
}
