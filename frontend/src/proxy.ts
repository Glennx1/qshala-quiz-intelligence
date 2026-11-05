import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Adds the backend API key to /api requests on the server, so it never has to ship to the browser as
// NEXT_PUBLIC_API_KEY. Set BACKEND_API_KEY (server-only) to the same value as the backend's API_KEY_SECRET.
// A no-op while BACKEND_API_KEY is unset, and a key the browser already sent is left as it is.
export function proxy(request: NextRequest) {
  const key = process.env.BACKEND_API_KEY;
  if (!key || request.headers.has("x-api-key")) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set("x-api-key", key);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
