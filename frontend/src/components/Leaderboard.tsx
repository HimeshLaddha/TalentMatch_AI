"use client";

import React, { useState, useEffect } from "react";

export interface Candidate {
  candidate_id: string;
  rank: number;
  score: number;
  reasoning?: string;
  years_of_experience: number;
  current_title: string;
  last_score?: number;
  final_score?: number;
  jd_multiplier?: number;
  jd_match_pct?: number;
  skills?: Array<string | { name: string }>;
  career_history?: Array<{ title: string; company: string; years?: number | null }>;
}

interface LeaderboardProps {
  candidates: Candidate[];
  jdActive?: boolean;
}

// Safe toFixed helper — never throws
function safeFixed(val: unknown, digits = 2): string {
  const n = Number(val);
  return isNaN(n) ? "—" : n.toFixed(digits);
}

export default function Leaderboard({ candidates, jdActive }: LeaderboardProps) {
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  // Lock body scroll when XAI drawer is open
  useEffect(() => {
    document.body.style.overflow = isDrawerOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [isDrawerOpen]);

  const openDrawer = (cand: Candidate) => {
    setSelectedCandidate(cand);
    setIsDrawerOpen(true);
  };

  const closeDrawer = () => {
    setIsDrawerOpen(false);
  };

  return (
    <div className="relative w-full border border-tm-border rounded-[12px] overflow-hidden bg-white select-none">

      {/* ── Desktop/Tablet table header — hidden on mobile ─────── */}
      <div className="hidden md:grid md:grid-cols-[44px_1fr_130px_70px_80px_90px] px-4 py-2.5 bg-tm-surface border-b border-tm-border text-[11px] text-tm-muted uppercase tracking-wider font-medium sticky top-0 z-10">
        <span>Rank</span>
        <span>Candidate</span>
        <span>Score</span>
        <span>YoE</span>
        {jdActive && <span>JD Match</span>}
        <span className="text-right">Action</span>
      </div>

      {/* ── Rows ────────────────────────────────────────────────── */}
      <div className="max-h-[600px] overflow-y-auto divide-y divide-tm-border">
        {candidates.map((cand) => {
          const isTop3 = cand.rank <= 3;
          const isRank1 = cand.rank === 1;

          const displayScore =
            jdActive && cand.final_score != null
              ? cand.final_score
              : (cand.last_score ?? cand.score);
          const baseScore = cand.last_score ?? cand.score;

          return (
            <div key={cand.candidate_id} className="hover:bg-tm-surface/50 transition-colors">

              {/* ── Mobile card layout ──────────────────────────── */}
              <div className="md:hidden p-4 flex items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <span
                    className="text-[13px] font-medium w-7 shrink-0 mt-0.5"
                    style={{ color: isRank1 ? "#B8820A" : isTop3 ? "var(--tm-text)" : "var(--tm-muted)" }}
                  >
                    #{cand.rank}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-tm-text truncate">
                      {cand.candidate_id}
                    </div>
                    <div className="text-[11px] text-tm-muted mt-0.5 truncate">
                      {cand.current_title} · {Math.round(cand.years_of_experience)} yrs
                    </div>
                    <div className="text-[12px] font-medium text-tm-text mt-1">
                      {safeFixed(displayScore, 2)}
                      {jdActive && baseScore != null && (
                        <span className="text-[10px] text-tm-muted font-normal ml-1">
                          base {safeFixed(baseScore, 2)}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => openDrawer(cand)}
                  className={`text-[11px] px-2.5 py-1 border border-tm-border rounded-[8px] transition-colors bg-white flex-shrink-0 ${
                    isTop3
                      ? "text-[#B8820A] border-[#B8820A]/30 hover:bg-[#B8820A]/5"
                      : "text-tm-text hover:bg-tm-surface"
                  }`}
                >
                  {isTop3 ? "Explain ✦" : "Explain"}
                </button>
              </div>

              {/* ── Desktop/Tablet grid row ─────────────────────── */}
              <div className="hidden md:grid md:grid-cols-[44px_1fr_130px_70px_80px_90px] px-4 py-3 items-center text-[13px] text-tm-text">
                {/* Rank */}
                <span
                  className="font-medium"
                  style={{ color: isRank1 ? "#B8820A" : isTop3 ? "var(--tm-text)" : "var(--tm-muted)" }}
                >
                  #{cand.rank}
                </span>

                {/* Candidate */}
                <div className="flex flex-col gap-0.5 min-w-0 pr-2">
                  <span className="font-medium text-[13px] text-tm-text truncate">
                    {cand.candidate_id}
                  </span>
                  <span className="text-[11px] text-tm-muted truncate">
                    {cand.current_title}
                  </span>
                </div>

                {/* Score */}
                <div className="flex flex-col gap-0.5 justify-center">
                  <div className="flex items-center gap-3 w-[130px]">
                    <div className="flex-1 h-2 bg-zinc-100 rounded-[2px] overflow-hidden">
                      <div
                        className="h-full bg-tm-accent"
                        style={{ width: `${Math.min(1.0, Math.max(0.0, displayScore)) * 100}%` }}
                      />
                    </div>
                    <span className="text-[12px] font-mono text-tm-text w-8 text-right shrink-0">
                      {safeFixed(displayScore, 2)}
                    </span>
                  </div>
                  {jdActive && baseScore != null && (
                    <span className="text-[10px] text-tm-muted pl-1">
                      base: {safeFixed(baseScore, 2)}
                    </span>
                  )}
                </div>

                {/* YoE */}
                <span className="inline-block bg-tm-surface text-[12px] text-tm-text px-2 py-0.5 border border-tm-border rounded-[20px] w-fit">
                  {Math.round(cand.years_of_experience)} yrs
                </span>

                {/* JD Match */}
                {jdActive ? (
                  <span>
                    {cand.jd_match_pct != null ? (
                      <span
                        className={`inline-block text-[11px] px-2 py-0.5 border rounded-[20px] font-medium ${
                          cand.jd_match_pct >= 61
                            ? "bg-emerald-50 text-emerald-700 border-emerald-200/50"
                            : cand.jd_match_pct >= 31
                            ? "bg-amber-50 text-amber-700 border-amber-200/50"
                            : "bg-zinc-100 text-zinc-700 border-zinc-200/50"
                        }`}
                      >
                        {cand.jd_match_pct}%
                      </span>
                    ) : (
                      <span className="text-[11px] text-tm-muted">—</span>
                    )}
                  </span>
                ) : (
                  <span />
                )}

                {/* Action */}
                <div className="text-right">
                  <button
                    onClick={() => openDrawer(cand)}
                    className={`text-[11px] px-2.5 py-1 border border-tm-border rounded-[8px] transition-colors bg-white ${
                      isTop3
                        ? "text-[#B8820A] border-[#B8820A]/30 hover:bg-[#B8820A]/5"
                        : "text-tm-text hover:bg-tm-surface"
                    }`}
                  >
                    {isTop3 ? "Explain ✦" : "Explain"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Drawer Overlay Backdrop ──────────────────────────────── */}
      {isDrawerOpen && (
        <div
          onClick={closeDrawer}
          className="fixed inset-0 bg-black/10 z-40 transition-opacity duration-300"
        />
      )}

      {/* ── Slide-over Drawer ────────────────────────────────────── */}
      <div
        className={[
          "fixed z-50 bg-white shadow-xl flex flex-col justify-between",
          "transition-transform duration-300 ease-out",
          // Mobile: full viewport
          "inset-0",
          // Tablet+: right-side sheet, full height
          "md:inset-y-0 md:left-auto md:right-0 md:w-[400px] md:border-l md:border-tm-border",
          isDrawerOpen ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-tm-border shrink-0">
          <div className="flex flex-col gap-1 min-w-0 pr-2">
            <span className="text-[11px] uppercase tracking-wider text-tm-muted">
              Candidate Analysis
            </span>
            <h3 className="text-lg font-medium text-tm-text truncate">
              {selectedCandidate?.candidate_id}
            </h3>
            <p className="text-[12px] text-tm-muted">
              {selectedCandidate?.current_title} · {selectedCandidate?.years_of_experience} yrs of experience
            </p>
          </div>
          <button
            onClick={closeDrawer}
            className="text-tm-muted hover:text-tm-text transition-colors p-1.5 rounded-lg hover:bg-tm-surface flex-shrink-0"
            aria-label="Close"
          >
            <i className="ti ti-x text-lg" />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 flex flex-col gap-4 overflow-y-auto px-5 py-4">

          <div className="border-t border-tm-border pt-4">
            <h4 className="text-[13px] font-medium text-tm-text mb-2">
              Explainable AI (XAI) Reasoning
            </h4>
            {selectedCandidate?.reasoning ? (
              // Has XAI reasoning — show it
              <div className="text-[13px] text-tm-text leading-[1.7] whitespace-pre-wrap font-normal">
                {selectedCandidate.reasoning}
              </div>
            ) : selectedCandidate && selectedCandidate.rank <= 3 ? (
              // Top-3 but reasoning not loaded yet
              <div className="text-[12px] text-tm-muted">
                Loading XAI reasoning… If this persists, re-run the pipeline to
                regenerate explanations for top candidates.
              </div>
            ) : (
              // Not top-3 — show candidate profile summary instead
              <div className="mt-1">
                <div className="text-[12px] text-tm-muted mb-3">
                  XAI reasoning is generated for top-3 candidates only.
                  Candidate profile summary:
                </div>
                {selectedCandidate?.skills && selectedCandidate.skills.length > 0 && (
                  <div className="mb-3">
                    <div className="text-[11px] font-medium text-tm-muted uppercase tracking-wide mb-1">
                      Skills
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {selectedCandidate.skills.slice(0, 10).map((sk, i) => (
                        <span
                          key={i}
                          className="text-[11px] px-2 py-0.5 rounded-full bg-tm-surface border border-tm-border text-tm-text"
                        >
                          {typeof sk === "string" ? sk : sk.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {selectedCandidate?.career_history && selectedCandidate.career_history.length > 0 && (
                  <div>
                    <div className="text-[11px] font-medium text-tm-muted uppercase tracking-wide mb-1">
                      Career History
                    </div>
                    {selectedCandidate.career_history.slice(0, 4).map((job, i) => (
                      <div
                        key={i}
                        className="text-[12px] py-1 border-b border-tm-border last:border-0 text-tm-text"
                      >
                        {job.title} @ {job.company}
                        {job.years != null && (
                          <span className="text-tm-muted ml-1">
                            · {Number(job.years).toFixed(1)} yrs
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="border-t border-tm-border px-5 py-4 shrink-0">
          <button
            onClick={closeDrawer}
            className="w-full text-center px-4 py-2 border border-tm-border rounded-[8px] text-[13px] text-tm-text hover:bg-tm-surface transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
