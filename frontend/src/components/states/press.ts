/** Instant press feedback for every pressable control (spec F.7, "Response"):
 *  a subtle scale on :active, transform only, 120ms with the house ease-out. */
export const PRESS_FEEDBACK =
  'transition-transform duration-[120ms] ease-out active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100';

/** The visible focus ring: a 2px outline in the text colour (monochrome, design docs system/tokens.md). */
export const FOCUS_RING =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fg';
