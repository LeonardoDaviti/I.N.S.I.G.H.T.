import { useMemo } from 'react';
import { docAt } from '../library';
import { channelsToHex, documentedTokens, rootValue, useRootClass } from './liveStyle';
import Section from './Section';

/**
 * The colour tokens, live (P2): the names and roles from the tokens doc's
 * table, the values from the running page. A documented token the page
 * doesn't define says so instead of showing a blank swatch (P11).
 */
export default function Tokens({ rules }: { rules?: string }) {
  const rootClass = useRootClass();
  const theme = rootClass.includes('theme-light') ? 'light' : 'dark';
  const tokens = useMemo(() => documentedTokens(docAt('/design/system/tokens')?.text ?? ''), []);
  return (
    <Section title="Colour tokens" rules={rules}>
      <p className="mb-4 text-[0.875rem] text-fg-2">
        Read now from the page in the <span className="font-semibold text-fg">{theme}</span> theme. Flip the theme (☾/☀) to read the other.
      </p>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="w-full border-collapse text-left text-[0.8125rem]">
          <thead className="sr-only">
            <tr><th>Token</th><th>Swatch</th><th>Role</th><th>Value</th></tr>
          </thead>
          <tbody>
            {tokens.map(({ name, role }) => {
              const value = rootValue(name);
              return (
                <tr key={name} className="border-b border-line last:border-b-0">
                  <td className="whitespace-nowrap py-2.5 pl-3 pr-4 font-mono text-[0.75rem] text-fg">{name}</td>
                  <td className="py-2 pr-4">
                    <span
                      aria-hidden="true"
                      className="block h-7 w-12 rounded-sm border border-line-strong"
                      style={value ? { background: `rgb(var(${name}))` } : undefined}
                    />
                  </td>
                  <td className="py-2.5 pr-4 text-fg-2">{role.replace(/`/g, '')}</td>
                  <td className="whitespace-nowrap py-2.5 pr-3 text-right font-mono text-[0.75rem] tabular-nums">
                    {value ? <span className="text-fg">{channelsToHex(value)}</span> : <span className="font-semibold text-fg">× not defined</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
