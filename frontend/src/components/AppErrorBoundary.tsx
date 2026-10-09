import { Component, type ErrorInfo, type ReactNode } from 'react';
import { errorMessage } from '../lib/apiError';
import { FOCUS_RING, PRESS_FEEDBACK } from './states/press';

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
      <div className="mx-auto max-w-xl px-6 py-16">
        <div
          role="alert"
          className="rounded-2xl border border-[var(--background-modifier-border)] bg-[var(--background-primary)] px-6 py-8 text-center"
        >
          <p className="text-base font-semibold text-[var(--text-normal)]">This page hit an error</p>
          <p className="mt-2 break-words text-sm text-[var(--text-error)]">{errorMessage(this.state.error)}</p>
          <div className="mt-5 flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={this.reset}
              className={`inline-flex min-h-[44px] items-center rounded-lg bg-[var(--interactive-accent)] px-4 text-sm font-medium text-[var(--text-on-accent)] hover:bg-[var(--interactive-accent-hover)] ${PRESS_FEEDBACK} ${FOCUS_RING}`}
            >
              Try again
            </button>
            <a
              href="/"
              className={`inline-flex min-h-[44px] items-center rounded-lg border border-[var(--background-modifier-border)] px-4 text-sm font-medium text-[var(--text-normal)] hover:bg-[var(--background-secondary)] ${PRESS_FEEDBACK} ${FOCUS_RING}`}
            >
              Go home
            </a>
          </div>
        </div>
      </div>
    );
  }
}
