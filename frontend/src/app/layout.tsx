// Server Component — no "use client" directive
// next/font/local MUST run in a Server Component (not in a "use client" file).
import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import AppShell from "@/components/AppShell";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "TalentMatch AI - Recruitment & Placement Engine",
  description:
    "End-to-end recruitment matching platform featuring multi-dimensional AI scoring and analysis.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-white text-tm-text min-h-screen`}
      >
        {/*
          AppShell is a "use client" component that manages:
          - Mobile sidebar open/close state
          - Hamburger topbar (mobile only)
          - Body scroll lock when sidebar is open
        */}
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
