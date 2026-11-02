import { Component, ErrorInfo, ReactNode } from "react";
import i18next from "i18next";
import { logger } from "@/utils/logger";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "./ui/Button";
import ErrorDetails from "./ErrorDetails";
import { isStaleChunkError } from "@/lib/staleChunk";

interface Props {
  children?: ReactNode;
  fallback?: ReactNode;
  variant?: "full" | "mini";
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Not a defect: the app is out of date behind a deploy (see staleChunk).
    if (isStaleChunkError(error)) return;
    logger.error("Uncaught error:", error, errorInfo);
  }

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      if (this.props.variant === "mini") {
        return (
          <div className="flex flex-col items-center justify-center p-4 border border-dashed border-red-200 rounded-lg bg-red-50 text-red-700 text-sm">
            <AlertCircle className="w-5 h-5 mb-2 opacity-50" />
            <p className="font-medium text-center">
              {i18next.t("common:errors.moduleError")}
            </p>
            <Button
              size="content"
              variant="link"
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-2 min-h-11 md:min-h-0 min-w-11 md:min-w-0 text-xs text-red-700 underline underline-offset-4 hover:text-red-900"
            >
              {i18next.t("common:errors.tryAgain")}
            </Button>
          </div>
        );
      }

      const stale = isStaleChunkError(this.state.error);

      return (
        <div className="flex flex-col items-center justify-center min-h-[400px] p-8 text-center bg-surface-card rounded-xl shadow-sm border border-border">
          <div className="w-16 h-16 bg-red-100 text-on-danger dark:bg-red-900/30 dark:text-red-300 rounded-full flex items-center justify-center mb-6">
            <AlertCircle className="w-10 h-10" />
          </div>
          <h1 className="text-2xl font-semibold text-on dark:text-white mb-2">
            {i18next.t(
              stale
                ? "common:errors.newVersionTitle"
                : "common:errors.somethingWentWrong",
            )}
          </h1>
          <p className="text-on-secondary dark:text-on-muted mb-8 max-w-md">
            {i18next.t(
              stale
                ? "common:errors.newVersionBody"
                : "common:errors.unexpectedError",
            )}
          </p>
          <div className="flex gap-4">
            <Button
              variant="outline"
              onClick={() => (window.location.href = "/")}
            >
              {i18next.t("common:errors.goHome")}
            </Button>
            <Button onClick={() => window.location.reload()}>
              <RefreshCw className="w-4 h-4 mr-2" />
              {i18next.t("common:errors.reloadPage")}
            </Button>
          </div>
          {this.state.error && !stale && (
            <ErrorDetails error={this.state.error} />
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
