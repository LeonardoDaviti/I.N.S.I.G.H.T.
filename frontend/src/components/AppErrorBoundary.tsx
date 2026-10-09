import { Component, type ErrorInfo, type ReactNode } from 'react';
import { errorMessage } from '../lib/apiError';
import Button from './ui/Button';
import { StatusIcon } from './ui/StatusGlyph';

type Props = {
  children: ReactNode;
  /** When this value changes (App passes the pathname) a caught error is cleared,
   *  so navigating away from a broken page recovers without a reload. */
  resetKey?: unknown;
};

type State = { error: unknown; hasError: boolean; resetKey: unknown };

/** The app-wide render error boundary: a crash in one page renders a recoverable
 *  message instead of unmounting the whole app to a blank screen. */
export default class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null, hasError: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error, hasError: true };
  }

  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (props.resetKey !== state.resetKey) {
      return { error: null, hasError: false, resetKey: props.resetKey };
    }
    return null;
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('Unhandled render error', error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null, hasError: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="mx-auto max-w-xl px-4 py-16 sm:px-6">
        <div role="alert" className="rounded-md border border-line-strong px-6 py-10 text-center">
          <span className="mx-auto inline-flex h-6 w-6 items-center justify-center rounded-sm bg-inverse text-inverse-fg">
            <StatusIcon status="failing" className="h-3 w-3" />
            <span className="sr-only">Error:</span>
          </span>
          <p className="mt-3 text-[1.0625rem] font-semibold tracking-[-0.01em] text-fg">This page hit an error</p>
          <p className="mt-1.5 break-words text-[0.875rem] text-fg-2 [overflow-wrap:anywhere]">{errorMessage(this.state.error)}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            <Button variant="primary" onClick={this.reset}>
              Try again
            </Button>
            <Button asChild variant="secondary">
              <a href="/">Go to feed</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
