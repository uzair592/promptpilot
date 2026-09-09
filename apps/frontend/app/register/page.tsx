"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

export default function RegisterPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (password.length < 12) {
      setError("Use at least 12 characters for your password.");
      return;
    }
    setLoading(true);
    const response = await fetch("http://localhost:8000/api/v1/auth/register", {
      method: "POST",
      credentials: "include",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        display_name: form.get("display_name"),
        password,
      }),
    });
    setLoading(false);
    if (!response.ok) {
      setError("We could not create that account.");
      return;
    }
    router.push("/dashboard");
  }
  return (
    <main className="shell">
      <section className="panel">
        <h1 className="brand">Create your workspace</h1>
        <p className="muted">Start building better context.</p>
        <form className="form" onSubmit={submit}>
          <label>
            Display name
            <input
              name="display_name"
              required
              maxLength={120}
              autoComplete="name"
            />
          </label>
          <label>
            Email
            <input name="email" type="email" required autoComplete="email" />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              required
              minLength={12}
              autoComplete="new-password"
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button disabled={loading}>
            {loading ? "Creating..." : "Create account"}
          </button>
        </form>
        <p className="muted">
          Already registered? <Link href="/login">Sign in</Link>
        </p>
      </section>
    </main>
  );
}
