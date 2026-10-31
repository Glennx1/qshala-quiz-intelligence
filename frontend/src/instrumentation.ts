// Server/edge-runtime Sentry init (QShala priority plan P2-1). Next.js calls register()
// automatically on boot; it must live next to src/app (not inside it) or production builds
// won't pick it up. Both imported config files are no-ops without SENTRY_DSN set.
import * as Sentry from '@sentry/nextjs';

export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('../sentry.server.config');
  }
  if (process.env.NEXT_RUNTIME === 'edge') {
    await import('../sentry.edge.config');
  }
}

export const onRequestError = Sentry.captureRequestError;
