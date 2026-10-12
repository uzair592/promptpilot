import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

function backendOrigin(): string {
  return (
    process.env.BACKEND_ORIGIN ??
    (process.env.NODE_ENV === "production" ? "" : "http://localhost:8000")
  );
}

export async function hasAuthenticatedSession(): Promise<boolean> {
  const cookieHeader = (await cookies()).toString();
  if (!cookieHeader) return false;

  const origin = backendOrigin();
  if (!origin) return false;

  try {
    const response = await fetch(`${origin}/api/v1/auth/me`, {
      cache: "no-store",
      headers: { cookie: cookieHeader },
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function requireAuthenticatedSession(): Promise<void> {
  if (!(await hasAuthenticatedSession())) redirect("/login");
}
