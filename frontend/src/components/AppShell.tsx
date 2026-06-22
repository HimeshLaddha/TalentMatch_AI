"use client";

import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import DbRecoveryProvider from "@/components/DbRecoveryProvider";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  // Lock body scroll when mobile sidebar is open
  useEffect(() => {
    document.body.style.overflow = mobileOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  return (
    <>
      {/*
        DbRecoveryProvider fires POST /profiles/sync-recovery exactly once
        per browser session on first mount, healing the in-memory Qdrant
        vector store from the persisted backend/storage/metadata.json
        registry regardless of which route the user lands on first.
      */}
      <DbRecoveryProvider />

      <div className="flex min-h-screen bg-tm-surface">
        <Sidebar
          mobileOpen={mobileOpen}
          onClose={() => setMobileOpen(false)}
        />

        {/* ── Main content area ─────────────────────────────── */}
        <div
          className={[
            "flex flex-col flex-1 min-w-0",
            // Mobile: no offset (sidebar is a floating overlay)
            "ml-0",
            // Tablet: offset by icon-sidebar width (56px = w-14)
            "md:ml-14",
            // Desktop: offset by full sidebar width (200px)
            "lg:ml-[200px]",
          ].join(" ")}
        >
          {/* Mobile topbar with hamburger — hidden on tablet+ */}
          <header className="md:hidden flex items-center gap-3 px-4 h-12 border-b border-tm-border bg-white sticky top-0 z-20 shrink-0">
            <button
              onClick={() => setMobileOpen(true)}
              className="text-tm-muted hover:text-tm-text p-1"
              aria-label="Open menu"
            >
              <i className="ti ti-menu-2 text-[22px]" />
            </button>
            <span className="font-semibold text-[15px] text-tm-text">
              TalentMatch <span className="font-normal text-tm-muted">AI</span>
            </span>
          </header>

          {/* Page content */}
          <main className="flex-1 h-screen overflow-y-auto bg-white relative flex flex-col">
            {children}
          </main>
        </div>
      </div>
    </>
  );
}
