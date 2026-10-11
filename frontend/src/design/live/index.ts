import type { ComponentType } from 'react';
import Tokens from './Tokens';
import TypeScale from './TypeScale';
import SpaceRadii from './SpaceRadii';
import Motion from './Motion';
import StatusVocabulary from './StatusVocabulary';

/** The live specimen that goes with each system doc, by the doc's slug, in the System page's order. */
export const SYSTEM_SPECIMENS: ReadonlyArray<readonly [slug: string, Specimen: ComponentType<{ rules?: string }>]> = [
  ['tokens', Tokens],
  ['typography', TypeScale],
  ['space-radii-layout', SpaceRadii],
  ['motion', Motion],
  ['status', StatusVocabulary],
];
