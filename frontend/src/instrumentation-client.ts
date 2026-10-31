// Browser-side Sentry init (QShala priority plan P2-1). Next.js loads this automatically on
// the client. No-op (Sentry.init is skipped) unless NEXT_PUBLIC_SENTRY_DSN is set -- this is
// the browser bundle, so only a NEXT_PUBLIC_ var is reachable here.
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,
  });
}

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
