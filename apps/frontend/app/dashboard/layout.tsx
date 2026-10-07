import { requireAuthenticatedSession } from "../../lib/server-auth";

export default async function DashboardLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  await requireAuthenticatedSession();
  return children;
}
