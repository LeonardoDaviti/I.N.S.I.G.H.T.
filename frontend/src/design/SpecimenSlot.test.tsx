import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import SpecimenSlot from './SpecimenSlot';

describe('<SpecimenSlot>', () => {
  it('frames the real page for a state with a fixture scenario, at its width and theme', () => {
    render(<SpecimenSlot page="reader" state="worst" width={390} theme="light" />);
    const frame = screen.getByTitle('reader · worst · 390px · light');
    expect(frame).toHaveAttribute('src', '/design/frame/reader/worst?theme=light&data=fixtures');
  });

  it('says so, without a frame, for a state no scenario covers yet (a parked page)', () => {
    render(<SpecimenSlot page="inbox" state="normal" width={1400} theme="dark" />);
    expect(screen.queryByTitle(/inbox/)).not.toBeInTheDocument();
    expect(screen.getByText(/No fixture scenario for inbox \/ normal yet/)).toBeInTheDocument();
  });
});
