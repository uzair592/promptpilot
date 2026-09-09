"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type User = { display_name: string; email: string };

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch("http://localhost:8000/api/v1/auth/me", { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          router.replace("/login");
          return;
        }
        const body = await response.json();
        setUser(body.user);
        setLoading(false);
      })
      .catch(() => router.replace("/login"));
  }, [router]);
  async function logout() {
    await fetch("http://localhost:8000/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    router.replace("/login");
  }
  if (loading)
    return (
      <main className="shell">
        <p className="muted">Loading your workspace...</p>
      </main>
    );
  return (
    <div className="nav">
      <aside className="sidebar">
        <h1>PromptPilot</h1>
        <p>Context engineering workspace</p>
      </aside>
      <main className="main">
        <div className="row">
          <div>
            <h2>Welcome, {user?.display_name}</h2>
            <p className="muted">{user?.email}</p>
          </div>
          <button className="secondary" onClick={logout}>
            Log out
          </button>
        </div>
        <section className="panel" style={{ marginTop: 32 }}>
          <h3>Projects</h3>
          <p className="muted">
            Projects will appear here in the next implementation slice.
          </p>
        </section>
      </main>
    </div>
  );
}
