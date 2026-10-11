/**
 * Bench mode (slice S5b): the checkout for a new design feature, two large
 * frames side by side (current page vs a prototype, or state vs state) with
 * the prototype's hypothesis, principles and status in a drawer. This is its
 * mount point; S5b replaces the body and keeps the default export.
 */
export default function BenchMode() {
  return (
    <section aria-label="Bench" className="mx-auto max-w-reading px-4 py-16 sm:px-6">
      <h1 className="text-[1.375rem] font-semibold leading-[1.25] tracking-[-0.02em] text-fg">Bench</h1>
      <p className="mt-3 text-fg-2">
        Two large frames side by side, the current page against a prototype on the same state, width and theme, with
        the hypothesis and the principles it serves. Not built yet (slice S5b).
      </p>
    </section>
  );
}
