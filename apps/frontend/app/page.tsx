import { redirect } from "next/navigation";

import { hasAuthenticatedSession } from "../lib/server-auth";

export default async function HomePage() {
  redirect((await hasAuthenticatedSession()) ? "/dashboard" : "/login");
}
