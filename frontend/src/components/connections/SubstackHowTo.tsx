import { ExternalLink } from '../ui';

/** The three steps to copy the substack.sid cookie, and what it is for (spec §10). */
export default function SubstackHowTo({ className = '' }: { className?: string }) {
  return (
    <div className={`space-y-2 text-[0.8125rem] text-fg-2 ${className}`}>
      <ol className="list-decimal space-y-1 pl-5 marker:tabular-nums marker:text-fg-3">
        <li>Log into <ExternalLink href="https://substack.com/sign-in">substack.com</ExternalLink> in this browser.</li>
        <li>Open DevTools → Application → Cookies → <span className="font-mono text-[0.75rem]">https://substack.com</span>.</li>
        <li>Copy the value of <span className="font-mono text-[0.75rem] text-fg">substack.sid</span> and paste it here.</li>
      </ol>
      <p className="text-[0.75rem] text-fg-3">
        For personal use of your own subscription. The cookie lasts months; it is stored encrypted and never shown again.
      </p>
    </div>
  );
}
