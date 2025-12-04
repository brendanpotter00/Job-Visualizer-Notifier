/**
 * Centralized logging utility
 *
 * Provides a consistent interface for logging throughout the application.
 * In development mode, all logs are output to the console.
 * In production, only warnings and errors are logged to prevent console clutter.
 *
 * Usage:
 *   import { logger } from '../utils/logger';
 *   logger.debug('[Component] Debug info');
 *   logger.info('[Component] Info message');
 *   logger.warn('[Component] Warning');
 *   logger.error('[Component] Error occurred', errorObject);
 */

// Check if we're in development mode
// In Vite, import.meta.env.DEV is available, but we'll use a try-catch for safety
let isDevelopment = false;
try {
  isDevelopment = (import.meta as any).env?.DEV ?? false;
} catch {
  isDevelopment = false;
}

export const logger = {
  /**
   * Debug logs - only shown in development
   * Use for detailed debugging information during development
   */
  debug: (...args: unknown[]): void => {
    if (isDevelopment) {
      console.log(...args);
    }
  },

  /**
   * Info logs - only shown in development
   * Use for general informational messages
   */
  info: (...args: unknown[]): void => {
    if (isDevelopment) {
      console.info(...args);
    }
  },

  /**
   * Warning logs - always shown
   * Use for recoverable errors or unexpected behavior
   */
  warn: (...args: unknown[]): void => {
    console.warn(...args);
  },

  /**
   * Error logs - always shown
   * Use for errors and exceptions
   */
  error: (...args: unknown[]): void => {
    console.error(...args);
  },
};
