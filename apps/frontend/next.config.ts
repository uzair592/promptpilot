import type { NextConfig } from "next";

function getBackendOrigin(): string {
  const configuredOrigin =
    process.env.BACKEND_ORIGIN ??
    (process.env.NODE_ENV === "production"
      ? undefined
      : "http://localhost:8000");
  if (!configuredOrigin) {
    throw new Error("BACKEND_ORIGIN is required for production builds");
  }

  let backend: URL;
  try {
    backend = new URL(configuredOrigin);
  } catch {
    throw new Error("BACKEND_ORIGIN must be a valid absolute URL");
  }
  if (
    backend.username ||
    backend.password ||
    backend.pathname !== "/" ||
    backend.search ||
    backend.hash ||
    (process.env.NODE_ENV === "production" && backend.protocol !== "https:")
  ) {
    throw new Error(
      "BACKEND_ORIGIN must be a secure origin without credentials or a path",
    );
  }
  return backend.origin;
}

const nextConfig: NextConfig = {
  // Next's standalone tracer creates pnpm symlinks that standard Windows
  // developer accounts cannot create. CI/deploy hosts retain standalone output.
  output: process.platform === "win32" ? undefined : "standalone",
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${getBackendOrigin()}/api/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/api/v1/:path*",
        headers: [{ key: "Cache-Control", value: "no-store" }],
      },
    ];
  },
};

export default nextConfig;
