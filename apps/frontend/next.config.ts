import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next's standalone tracer creates pnpm symlinks that standard Windows
  // developer accounts cannot create. CI/deploy hosts retain standalone output.
  output: process.platform === "win32" ? undefined : "standalone",
};

export default nextConfig;
