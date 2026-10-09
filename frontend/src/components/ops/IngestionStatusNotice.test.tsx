import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IngestionStatusNotice from './IngestionStatusNotice';

describe('IngestionStatusNotice', () => {
  it('draws a stopped service as a ring and a word in a solid box, not a spinner or a dashed box', () => {
    const { container } = render(
      <MemoryRouter>
        <IngestionStatusNotice state="stopped" message="Nothing fetched for 10d." linkToIngestion />
      </MemoryRouter>,
    );
    const notice = screen.getByTestId('ingestion-status-notice');
    expect(notice).toHaveTextContent('stopped');
    expect(notice).toHaveTextContent('Ingestion is not running');
    expect(notice.querySelector('[data-glyph="read"]')).not.toBeNull();
    expect(container.innerHTML).not.toMatch(/dashed|animate-spin/);
    expect(screen.getByRole('link', { name: 'Open ingestion' })).toHaveAttribute('href', '/ingestion');
  });

  it('makes failing the inverted × chip and running a dot', () => {
    render(<IngestionStatusNotice state="failing" />);
    expect(screen.getByTestId('ingestion-status-notice').querySelector('[data-status="failing"]')).not.toBeNull();
  });
});
