// Node.js server-side Sentry init (QShala priority plan P2-1), imported by instrumentation.ts
// when NEXT_RUNTIME=nodejs. No-op unless SENTRY_DSN is set -- this runs server-side only, so a
// plain (non-NEXT_PUBLIC_) env var is fine and keeps it out of the browser bundle.
import * as Sentry from '@sentry/nextjs';

const dsn = process.env.SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    tracesSampleRate: process.env.NODE_ENV === 'production' ? 0.1 : 1.0,
  });
}
