import { describe, expect, it, vi } from "vitest";

import {
  logout,
  validateLogin,
  validateRegistration,
} from "../apps/frontend/lib/auth.js";

describe("frontend authentication helpers", () => {
  it("validates registration fields", () => {
    expect(
      validateRegistration({
        email: "bad",
        displayName: "",
        password: "short",
      }),
    ).toBe("Enter a valid email address.");
    expect(
      validateRegistration({
        email: "user@example.com",
        displayName: "User",
        password: "short",
      }),
    ).toBe("Use at least 12 characters for your password.");
    expect(
      validateRegistration({
        email: "user@example.com",
        displayName: "User",
        password: "long enough password",
      }),
    ).toBeNull();
  });

  it("validates login fields", () => {
    expect(validateLogin({ email: "bad", password: "secret" })).toBe(
      "Enter a valid email address.",
    );
    expect(validateLogin({ email: "user@example.com", password: "" })).toBe(
      "Enter your password.",
    );
    expect(
      validateLogin({ email: "user@example.com", password: "secret" }),
    ).toBeNull();
  });

  it("logs out through the authenticated API boundary", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response(null, { status: 204 }));
    await logout("http://localhost:8000");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/auth/logout",
      {
        method: "POST",
        credentials: "include",
      },
    );
    fetchMock.mockRestore();
  });
});
