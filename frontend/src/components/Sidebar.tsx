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
    {
      name: "Recruitment Dashboard",
      href: "/admin",
      description: "Match & rank candidates",
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" />
        </svg>
      ),
    },
    {
      name: "Candidate Portal",
      href: "/user",
      description: "Ingest profiles & metrics",
      icon: (
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
        </svg>
      ),
    },
  ];

  return (
    <aside className="w-72 bg-slate-950 border-r border-slate-800/80 flex flex-col h-screen select-none">
      {/* Brand Header */}
      <div className="p-6 border-b border-slate-800/80">
        <Link href="/admin" className="flex items-center gap-3 group">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 flex items-center justify-center shadow-lg shadow-indigo-500/20 group-hover:scale-105 transition-transform duration-300">
            <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
              <path d="M13 6a3 3 0 11-6 0 3 3 0 016 0zM18 8a2 2 0 11-4 0 2 2 0 014 0zM14 15a4 4 0 00-8 0v3h8v-3zM6 8a2 2 0 11-4 0 2 2 0 014 0zM16 18v-3a5.972 5.972 0 00-.75-2.906A3.005 3.005 0 0119 15v3h-3zM4.75 12.094A5.973 5.973 0 004 15v3H1v-3a3 3 0 013.75-2.906z" />
            </svg>
          </div>
          <div>
            <h1 className="text-lg font-bold bg-gradient-to-r from-slate-100 to-slate-300 bg-clip-text text-transparent">
              TalentMatch AI
            </h1>
            <p className="text-xs text-slate-500 font-medium">Recruitment Engine</p>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-start gap-4 p-3.5 rounded-xl transition-all duration-200 group ${
                isActive
                  ? "bg-slate-900 text-indigo-400 border border-indigo-500/20 shadow-inner shadow-indigo-500/5"
                  : "text-slate-400 hover:bg-slate-900/50 hover:text-slate-200 border border-transparent"
              }`}
            >
              <div className={`mt-0.5 transition-colors ${isActive ? "text-indigo-400" : "text-slate-400 group-hover:text-slate-200"}`}>
                {item.icon}
              </div>
              <div>
                <div className="font-semibold text-sm leading-none">{item.name}</div>
                <div className={`text-xs mt-1 transition-colors ${isActive ? "text-slate-400" : "text-slate-500 group-hover:text-slate-400"}`}>
                  {item.description}
                </div>
              </div>
            </Link>
          );
        })}
      </nav>

      {/* User & Health Footer */}
      <div className="p-4 border-t border-slate-800/80 bg-slate-950/80 flex flex-col gap-4">
        {/* User Card */}
        <div className="flex items-center gap-3 p-2 rounded-lg bg-slate-900/30">
          <div className="w-10 h-10 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center font-bold text-slate-300">
            HL
          </div>
          <div className="overflow-hidden">
            <div className="text-sm font-semibold text-slate-200 truncate">Himesh Laddha</div>
            <div className="text-xs text-slate-500 truncate">Talent Acquisition</div>
          </div>
        </div>

        {/* Health Check Bar */}
        <div className="flex items-center justify-between text-xs px-2">
          <span className="text-slate-500 font-medium">Backend Server</span>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                isBackendHealthy === null ? "bg-amber-400" : isBackendHealthy ? "bg-emerald-400" : "bg-rose-400"
              }`}></span>
              <span className={`relative inline-flex rounded-full h-2 w-2 ${
                isBackendHealthy === null ? "bg-amber-500" : isBackendHealthy ? "bg-emerald-500" : "bg-rose-500"
              }`}></span>
            </span>
            <span className={`font-semibold ${
              isBackendHealthy === null ? "text-amber-500" : isBackendHealthy ? "text-emerald-400" : "text-rose-400"
            }`}>
              {isBackendHealthy === null ? "Checking..." : isBackendHealthy ? "Connected" : "Offline"}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
