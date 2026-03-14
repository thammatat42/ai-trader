import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Check for access token in cookies or just let client-side handle it.
  // Since we store tokens in localStorage (client-side only), we can't
  // check them in middleware. Instead, we redirect unauthenticated users
  // from the dashboard layout using the useAuth hook.
  // This middleware just ensures /login is accessible without redirect loops.
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|logo.svg).*)"],
};
