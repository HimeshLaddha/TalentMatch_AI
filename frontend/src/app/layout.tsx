import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import DbRecoveryProvider from "@/components/DbRecoveryProvider";

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
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-white text-tm-text min-h-screen`}
      >
        {/*
          DbRecoveryProvider fires POST /profiles/sync-recovery exactly once
          per browser session on first mount, healing the in-memory Qdrant
          vector store from the persisted backend/storage/metadata.json
          registry regardless of which route the user lands on first.
        */}
        <DbRecoveryProvider />

        <div className="flex h-screen w-screen overflow-hidden bg-white">
          <Sidebar />
          <main className="flex-1 h-screen overflow-y-auto bg-white relative flex flex-col">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
