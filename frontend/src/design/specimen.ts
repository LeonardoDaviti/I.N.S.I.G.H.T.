/** The specimen's vocabulary (D4), shared by the Handbook's slot and its controls and by Bench. */
export type SpecimenTheme = 'dark' | 'light';

/** A desktop window and a phone; a state may add its own (the 320px top bar). The first of each is the default. */
export const SPECIMEN_WIDTHS: readonly number[] = [1400, 390];
export const SPECIMEN_THEMES: readonly SpecimenTheme[] = ['dark', 'light'];

export interface SpecimenSlotProps {
  /** The page doc's slug: `reader`, `post`, `inbox`. */
  page: string;
  /** One of the doc's `states:`. */
  state: string;
  /** In CSS px: one of SPECIMEN_WIDTHS or the state's own. */
  width: number;
  theme: SpecimenTheme;
}
