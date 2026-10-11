/**
 * Wall mode (slice S4): the whole website as one wall, every page in use at
 * its normal state in navigation order, the links between them drawn and
 * labelled, P-chips and a walk replay. This is its mount point; S4 replaces
 * the body and keeps the default export.
 */
export default function WallMode() {
  return (
    <section aria-label="Wall" className="mx-auto max-w-reading px-4 py-16 sm:px-6">
      <h1 className="text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">Wall</h1>
      <p className="mt-3 text-fg-2">
        The whole site as one wall: every page in use at its normal state, in the order you navigate it, with the links
        between them labelled by what you click. Not built yet (slice S4).
      </p>
    </section>
  );
}
