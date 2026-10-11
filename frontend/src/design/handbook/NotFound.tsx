import TextLink from '../../components/ui/TextLink';

/** An unknown studio URL: say so, and the way back (P11). */
export default function NotFound({ what = 'page' }: { what?: string }) {
  return (
    <div className="mx-auto max-w-reading">
      <h1 className="text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">Not in the studio</h1>
      <p className="mt-3 text-fg-2">
        No {what} lives at this address. <TextLink to="/design">Back to the principles</TextLink>
      </p>
    </div>
  );
}
