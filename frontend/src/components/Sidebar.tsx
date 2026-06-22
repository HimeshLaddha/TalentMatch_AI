"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

const NAV = [
  { href: "/dashboard",  icon: "ti-chart-bar", label: "Rankings"   },
  { href: "/upload",     icon: "ti-upload",    label: "Upload"     },
  { href: "/candidates", icon: "ti-users",     label: "Candidates" },
  { href: "/settings",   icon: "ti-settings",  label: "Settings"   },
  { href: "/admin",      icon: "ti-shield",    label: "Admin"      },
];

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export default function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const pathname = usePathname();
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean | null>(null);

  // Backend health-check (preserved from original Sidebar)
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch("http://localhost:8000/health");
        if (res.ok) {
          const data = await res.json();
          setIsBackendHealthy(data.status === "healthy");
        } else {
          setIsBackendHealthy(false);
        }
      } catch {
        setIsBackendHealthy(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      {/* ── Mobile backdrop ─────────────────────────────────────── */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-30 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      {/* ── Sidebar panel ───────────────────────────────────────── */}
      <aside
        className={[
          // Base
          "fixed top-0 left-0 h-full z-40 flex flex-col select-none",
          "bg-tm-surface border-r border-tm-border",
          "transition-transform duration-200 ease-in-out",
          // Mobile: 240px wide drawer, hidden off-screen by default
          "w-[240px]",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          // Tablet md (768-1023px): always visible, icon-only (56px)
          "md:translate-x-0 md:w-14",
          // Desktop lg (1024px+): full sidebar (200px)
          "lg:w-[200px]",
        ].join(" ")}
      >
        {/* Logo row */}
        <div className="flex items-center gap-2 px-3 h-12 border-b border-tm-border shrink-0">
          <Link href="/dashboard" className="flex items-center gap-1.5 min-w-0">
            {/* Full text — mobile drawer + desktop */}
            <span className="text-sm font-medium text-tm-text lg:block md:hidden block truncate">
              TalentMatch <span className="font-normal text-tm-muted">AI</span>
            </span>
            {/* "T" monogram — tablet icon-only mode */}
            <span className="text-sm font-bold text-tm-text lg:hidden md:block hidden">
              T
            </span>
          </Link>

          {/* Close button — mobile only */}
          <button
            onClick={onClose}
            className="ml-auto md:hidden text-tm-muted hover:text-tm-text p-1 flex-shrink-0"
            aria-label="Close menu"
          >
            <i className="ti ti-x text-[18px]" />
          </button>
        </div>

        {/* Nav items */}
        <nav className="flex flex-col gap-1 p-2 flex-1 overflow-y-auto">
          {NAV.map((item) => {
            const active =
              pathname === item.href ||
              (item.href === "/dashboard" && pathname === "/") ||
              pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={[
                  "flex items-center gap-2 px-3 py-2 rounded-[8px]",
                  "text-[13px] transition-colors relative group",
                  active
                    ? "bg-white text-tm-text font-medium border border-tm-border"
                    : "text-tm-muted hover:bg-white hover:text-tm-text border border-transparent",
                ].join(" ")}
              >
                <i className={`ti ${item.icon} text-base flex-shrink-0`} />

                {/* Label: visible on mobile + desktop, hidden tablet */}
                <span className="lg:block md:hidden block">{item.label}</span>

                {/* Tooltip shown on tablet (icon-only mode) */}
                <span
                  className={[
                    "absolute left-[52px] px-2 py-1 rounded-[6px] whitespace-nowrap",
                    "bg-tm-text text-white text-[11px]",
                    "opacity-0 group-hover:opacity-100 pointer-events-none",
                    "transition-opacity duration-100 z-50",
                    "lg:hidden md:block hidden",
                  ].join(" ")}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* Backend health indicator */}
        <div className="p-3 border-t border-tm-border shrink-0">
          {/* Full status — mobile + desktop */}
          <div className="flex items-center justify-between text-[11px] text-tm-muted lg:flex md:hidden flex">
            <span>Backend</span>
            <div className="flex items-center gap-1.5">
              <span
                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  isBackendHealthy === null
                    ? "bg-amber-500"
                    : isBackendHealthy
                    ? "bg-tm-success"
                    : "bg-rose-500"
                }`}
              />
              <span className="font-medium text-tm-text">
                {isBackendHealthy === null
                  ? "Checking..."
                  : isBackendHealthy
                  ? "Online"
                  : "Offline"}
              </span>
            </div>
          </div>
          {/* Dot-only — tablet */}
          <div className="lg:hidden md:flex hidden items-center justify-center">
            <span
              title={
                isBackendHealthy === null
                  ? "Checking backend..."
                  : isBackendHealthy
                  ? "Backend online"
                  : "Backend offline"
              }
              className={`w-2 h-2 rounded-full ${
                isBackendHealthy === null
                  ? "bg-amber-500"
                  : isBackendHealthy
                  ? "bg-tm-success"
                  : "bg-rose-500"
              }`}
            />
          </div>
        </div>
      </aside>
    </>
  );
}
