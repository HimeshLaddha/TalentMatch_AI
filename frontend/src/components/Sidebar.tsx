"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

export default function Sidebar() {
  const pathname = usePathname();
  const [isBackendHealthy, setIsBackendHealthy] = useState<boolean | null>(null);

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

  const navItems = [
    { name: "Rankings", href: "/dashboard", icon: "ti-chart-bar" },
    { name: "Upload", href: "/upload", icon: "ti-upload" },
    { name: "Candidates", href: "/candidates", icon: "ti-users" },
    { name: "Settings", href: "/settings", icon: "ti-settings" },
    { name: "Admin", href: "/admin", icon: "ti-shield" },
  ];

  return (
    <aside className="w-[200px] shrink-0 bg-tm-surface border-r border-tm-border flex flex-col h-screen select-none">
      {/* Brand Header */}
      <div className="h-12 px-4 flex items-center border-b border-tm-border">
        <Link href="/dashboard" className="flex items-center gap-1.5">
          <span className="text-sm font-medium text-tm-text">TalentMatch</span>
          <span className="text-sm text-tm-muted">AI</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-2 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href || (item.href === "/dashboard" && pathname === "/");
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2 px-3 py-2 rounded-[8px] text-[13px] transition-colors ${
                isActive
                  ? "bg-white text-tm-text font-medium border border-tm-border"
                  : "text-tm-muted hover:bg-white hover:text-tm-text border border-transparent"
              }`}
            >
              <i className={`ti ${item.icon} text-base`} />
              <span>{item.name}</span>
            </Link>
          );
        })}
      </nav>

      {/* Health Indicator */}
      <div className="p-3 border-t border-tm-border flex items-center justify-between text-[11px] text-tm-muted">
        <span>Backend</span>
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${
            isBackendHealthy === null ? "bg-amber-500" : isBackendHealthy ? "bg-tm-success" : "bg-rose-500"
          }`} />
          <span className="font-medium text-tm-text">
            {isBackendHealthy === null ? "Checking..." : isBackendHealthy ? "Online" : "Offline"}
          </span>
        </div>
      </div>
    </aside>
  );
}
