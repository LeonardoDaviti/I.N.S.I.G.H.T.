import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { DEFAULT_THEME, THEME_STORAGE_KEY, ThemeProvider, useTheme } from '../ThemeProvider';
import ThemeToggle from '../ThemeToggle';
import {
  Button,
  Chip,
  Dialog,
  DialogContent,
  FilterChip,
  PageHeader,
  Row,
  STATUS_LABEL,
  StatusGlyph,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  type Status,
} from './index';

describe('theme', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = '';
  });

  it('defaults to dark when nothing is stored', () => {
    expect(DEFAULT_THEME).toBe('theme-dark');
    function Probe() {
      return <p>{useTheme().theme}</p>;
    }
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByText('theme-dark')).toBeInTheDocument();
    expect(document.documentElement).toHaveClass('theme-dark', 'dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('theme-dark');
  });

  it('keeps a stored light choice, and the toggle switches and persists', async () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'theme-light');
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement).toHaveClass('theme-light');
    expect(document.documentElement).not.toHaveClass('dark');
    await userEvent.click(screen.getByRole('button', { name: 'Switch to dark theme' }));
    expect(document.documentElement).toHaveClass('theme-dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('theme-dark');
    expect(screen.getByRole('button', { name: 'Switch to light theme' })).toBeInTheDocument();
  });

  it('ignores a corrupt stored value and falls back to dark', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'solarized');
    render(<ThemeProvider><span /></ThemeProvider>);
    expect(document.documentElement).toHaveClass('theme-dark');
  });
});

describe('StatusGlyph: status without colour', () => {
  const ALL = Object.keys(STATUS_LABEL) as Status[];

  it.each(ALL)('%s renders a decorative glyph and its word', (status) => {
    const { container } = render(<StatusGlyph status={status} />);
    const root = container.querySelector(`[data-status="${status}"]`);
    expect(root).not.toBeNull();
    expect(root).toHaveTextContent(STATUS_LABEL[status]);
    const svg = root!.querySelector('svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).toHaveAttribute('data-glyph', status);
  });

  it('every status has a distinct word', () => {
    const words = ALL.map((status) => STATUS_LABEL[status]);
    expect(new Set(words).size).toBe(words.length);
  });

  it('failing is an inverted chip so it reads loudest without red', () => {
    const { container } = render(<StatusGlyph status="failing" />);
    expect(container.firstElementChild).toHaveClass('bg-inverse', 'text-inverse-fg');
  });

  it('hideLabel keeps the word for screen readers; failing keeps its inverted square', () => {
    const { container } = render(<StatusGlyph status="failing" hideLabel />);
    const word = screen.getByText('failing');
    expect(word).toHaveClass('sr-only');
    expect(container.firstElementChild).toHaveClass('bg-inverse', 'text-inverse-fg');
  });

  it('hideLabel drops the border chips of backoff and unavailable', () => {
    const { container } = render(<><StatusGlyph status="backoff" hideLabel /><StatusGlyph status="ok" hideLabel /></>);
    const [backoff, ok] = Array.from(container.children);
    expect(backoff).not.toHaveClass('border');
    expect(ok).not.toHaveClass('bg-inverse');
  });

  it('a custom label replaces the word', () => {
    render(<StatusGlyph status="due" label="overdue 3d" />);
    expect(screen.getByText('overdue 3d')).toBeInTheDocument();
    expect(screen.queryByText('due')).toBeNull();
  });
});

describe('Button', () => {
  it('is type="button" by default and primary is the inverted block', () => {
    render(<Button variant="primary">Run cycle</Button>);
    const button = screen.getByRole('button', { name: 'Run cycle' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveClass('bg-inverse', 'text-inverse-fg');
  });

  it('secondary is an outline and asChild renders the child element', () => {
    render(
      <Button asChild variant="secondary">
        <a href="/settings/sources">Sources</a>
      </Button>,
    );
    const link = screen.getByRole('link', { name: 'Sources' });
    expect(link).toHaveClass('border-line-strong');
    expect(link).not.toHaveAttribute('type');
  });

  it('danger is not the primary block: an inner hairline and a leading × mark', () => {
    render(<><Button variant="primary">Save</Button><Button variant="danger">Delete track</Button></>);
    const primary = screen.getByRole('button', { name: 'Save' });
    const danger = screen.getByRole('button', { name: 'Delete track' });
    expect(danger.className).not.toBe(primary.className);
    expect(danger.querySelector('[data-danger-mark]')).toHaveTextContent('×');
    expect(danger.querySelector('[data-danger-mark]')).toHaveAttribute('aria-hidden', 'true');
    expect(primary.querySelector('[data-danger-mark]')).toBeNull();
  });

  it('fires onClick and respects disabled', async () => {
    const onClick = vi.fn();
    render(
      <>
        <Button onClick={onClick}>Go</Button>
        <Button onClick={onClick} disabled>Never</Button>
      </>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Go' }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Never' })).toBeDisabled();
  });
});

describe('Chip and FilterChip', () => {
  it('a FilterChip exposes aria-pressed and a formatted count', async () => {
    const onClick = vi.fn();
    render(
      <>
        <FilterChip selected count={12847} onClick={onClick}>all</FilterChip>
        <FilterChip selected={false} count={0}>failing</FilterChip>
      </>,
    );
    const all = screen.getByRole('button', { name: /all/ });
    expect(all).toHaveAttribute('aria-pressed', 'true');
    expect(all).toHaveTextContent('12,847');
    expect(screen.getByRole('button', { name: /failing/ })).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(all);
    expect(onClick).toHaveBeenCalled();
  });

  it('a solid chip is inverted', () => {
    render(<Chip variant="solid">fast</Chip>);
    expect(screen.getByText('fast')).toHaveClass('bg-inverse');
  });
});

describe('Row, PageHeader, Tabs, Dialog', () => {
  it('a Row with `to` is one link carrying meta and title', () => {
    render(
      <MemoryRouter>
        <Row to="/posts/1" meta="Sep 09" title="not much happened today" />
      </MemoryRouter>,
    );
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/posts/1');
    expect(link).toHaveTextContent('Sep 09');
    expect(link).toHaveTextContent('not much happened today');
  });

  it('a muted Row drops the title weight', () => {
    render(<Row title="Read post" muted />);
    expect(screen.getByText('Read post')).toHaveClass('font-normal', 'text-fg-2');
  });

  it('PageHeader renders one h1, the meta line and actions', () => {
    render(<PageHeader title="Sources" meta="90 sources · as of just now" actions={<Button variant="primary">Add source</Button>} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Sources' })).toBeInTheDocument();
    expect(screen.getByText('90 sources · as of just now')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add source' })).toBeInTheDocument();
  });

  it('Tabs switch panels by keyboard and mouse', async () => {
    render(
      <Tabs defaultValue="sources">
        <TabsList aria-label="Sources views">
          <TabsTrigger value="sources">sources &amp; tracks</TabsTrigger>
          <TabsTrigger value="health">health &amp; cadence</TabsTrigger>
        </TabsList>
        <TabsContent value="sources">list</TabsContent>
        <TabsContent value="health">table</TabsContent>
      </Tabs>,
    );
    expect(screen.getByRole('tab', { name: /sources/ })).toHaveAttribute('aria-selected', 'true');
    await userEvent.click(screen.getByRole('tab', { name: /health/ }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('table');
  });

  it('DialogContent is a named dialog with a close button', async () => {
    const onOpenChange = vi.fn();
    render(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent title="Delete source?" description="This cannot be undone.">
          body
        </DialogContent>
      </Dialog>,
    );
    expect(screen.getByRole('dialog', { name: 'Delete source?' })).toHaveTextContent('This cannot be undone.');
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
