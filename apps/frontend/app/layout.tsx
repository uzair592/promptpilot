import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PromptPilot",
  description: "Turn rough ideas into clear, high-quality prompts",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
