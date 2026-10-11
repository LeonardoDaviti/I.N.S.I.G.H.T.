/** The specimen's vocabulary (D4), shared by the slot, its controls and S3's frames. */
export type SpecimenWidth = 1400 | 390;
export type SpecimenTheme = 'dark' | 'light';

/** The first of each is the default. */
export const SPECIMEN_WIDTHS: readonly SpecimenWidth[] = [1400, 390];
export const SPECIMEN_THEMES: readonly SpecimenTheme[] = ['dark', 'light'];

export interface SpecimenSlotProps {
  /** The page doc's slug: `reader`, `post`, `inbox`. */
  page: string;
  /** One of the doc's `states:`. */
  state: string;
  width: SpecimenWidth;
  theme: SpecimenTheme;
}
