"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function useGuestRoute(): void {
  const router = useRouter();

  useEffect(() => {
    let active = true;
    fetch("/api/v1/auth/me", { credentials: "include" })
      .then((response) => {
        if (active && response.ok) router.replace("/dashboard");
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [router]);
}
