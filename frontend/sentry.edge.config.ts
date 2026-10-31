// Edge-runtime Sentry init (QShala priority plan P2-1), imported by instrumentation.ts when
// NEXT_RUNTIME=edge (middleware, edge API routes). No-op unless SENTRY_DSN is set.
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,
    sendDefaultPii: false,
  });
}
