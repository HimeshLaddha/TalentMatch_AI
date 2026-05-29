import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Sidebar from "@/components/Sidebar";

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
  description: "End-to-end recruitment matching platform featuring multi-dimensional AI scoring and analysis.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-slate-950 text-slate-100 min-h-screen`}
      >
        <div className="flex h-screen w-screen overflow-hidden bg-slate-950">
          <Sidebar />
          <main className="flex-1 h-screen overflow-y-auto bg-slate-900/40 relative">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}

