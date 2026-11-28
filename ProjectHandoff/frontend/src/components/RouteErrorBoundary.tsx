import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  label: string;
}

interface State {
  error: Error | null;
}

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`${this.props.label} failed to render`, error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="mx-auto max-w-xl p-6">
        <div className="card-base p-6">
          <h1 className="text-lg font-semibold text-stone-900 dark:text-stone-50">{this.props.label} could not load</h1>
          <p className="mt-2 text-sm text-stone-600 dark:text-stone-300">
            {this.state.error.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white dark:bg-stone-100 dark:text-stone-900"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
