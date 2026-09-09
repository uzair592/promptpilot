export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  status: string;
};

export function validateRegistration(input: {
  email: string;
  displayName: string;
  password: string;
}): string | null {
  if (!input.email.includes("@")) return "Enter a valid email address.";
  if (!input.displayName.trim()) return "Enter your display name.";
  if (input.password.length < 12)
    return "Use at least 12 characters for your password.";
  return null;
}

export function validateLogin(input: {
  email: string;
  password: string;
}): string | null {
  if (!input.email.includes("@")) return "Enter a valid email address.";
  if (!input.password) return "Enter your password.";
  return null;
}

export async function logout(apiBaseUrl: string): Promise<void> {
  await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
}
