import { requireAuthenticatedSession } from "../../lib/server-auth";

export default async function ProjectsLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  await requireAuthenticatedSession();
  return children;
}
