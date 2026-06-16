"use client";

import React, { useState } from "react";

export interface Candidate {
  candidate_id: string;
  rank: number;
  score: number;
  reasoning: string;
  years_of_experience: number;
  current_title: string;
  last_score?: number;
  final_score?: number;
  jd_multiplier?: number;
  jd_match_pct?: number;
}

interface LeaderboardProps {
  candidates: Candidate[];
  jdActive?: boolean;
}

export default function Leaderboard({ candidates, jdActive }: LeaderboardProps) {
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  const openDrawer = (cand: Candidate) => {
    setSelectedCandidate(cand);
    setIsDrawerOpen(true);
  };

  const closeDrawer = () => {
    setIsDrawerOpen(false);
  };

  return (
    <div className="relative w-full border border-tm-border rounded-[12px] overflow-hidden bg-white select-none">
      {/* Table Container with scroll support */}
      <div className="max-h-[600px] overflow-y-auto">
        <table className="w-full text-left border-collapse">
          <thead className="sticky top-0 bg-tm-surface z-10 text-[11px] uppercase tracking-wider text-tm-muted border-b border-tm-border">
            <tr>
              <th className="p-3 pl-4 font-medium">Rank</th>
              <th className="p-3 font-medium">Candidate</th>
              <th className="p-3 font-medium">Score</th>
              {jdActive && <th className="p-3 font-medium">JD Match</th>}
              <th className="p-3 font-medium">Experience</th>
              <th className="p-3 pr-4 font-medium text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-tm-border text-[13px] text-tm-text">
            {candidates.map((cand) => {
              const isTop3 = cand.rank <= 3;
              const isRank1 = cand.rank === 1;

              const displayScore = jdActive && cand.final_score != null
                ? cand.final_score
                : (cand.last_score ?? cand.score);

              const baseScore = cand.last_score ?? cand.score;

              return (
                <tr key={cand.candidate_id} className="hover:bg-tm-surface/50 transition-colors">
                  {/* Rank Column */}
                  <td className="p-3 pl-4 font-medium">
                    <span
                      style={{
                        color: isRank1 ? "#B8820A" : isTop3 ? "var(--tm-text)" : "var(--tm-muted)",
                      }}
                    >
                      #{cand.rank}
                    </span>
                  </td>

                  {/* Candidate Column */}
                  <td className="p-3">
                    <div className="flex flex-col gap-0.5">
                      <span className="font-medium text-[13px] text-tm-text">
                        {cand.candidate_id}
                      </span>
                      <span className="text-[11px] text-tm-muted">
                        {cand.current_title}
                      </span>
                    </div>
                  </td>

                  {/* Score Column */}
                  <td className="p-3">
                    <div className="flex flex-col gap-0.5 justify-center">
                      <div className="flex items-center gap-3 w-[150px]">
                        <div className="flex-1 h-2 bg-zinc-100 rounded-[2px] overflow-hidden">
                          <div
                            className="h-full bg-tm-accent"
                            style={{ width: `${Math.min(1.0, Math.max(0.0, displayScore)) * 100}%` }}
                          />
                        </div>
                        <span className="text-[12px] font-mono text-tm-text w-8 text-right shrink-0">
                          {displayScore.toFixed(2)}
                        </span>
                      </div>
                      {jdActive && baseScore != null && (
                        <span className="text-[10px] text-tm-muted pl-1">
                          base: {baseScore.toFixed(2)}
                        </span>
                      )}
                    </div>
                  </td>

                  {/* JD Match Column */}
                  {jdActive && (
                    <td className="p-3">
                      {cand.jd_match_pct != null ? (
                        (() => {
                          const pct = cand.jd_match_pct;
                          let pillClass = "bg-zinc-100 text-zinc-700 border-zinc-200/50";
                          if (pct >= 31 && pct <= 60) {
                            pillClass = "bg-amber-50 text-amber-700 border-amber-200/50";
                          } else if (pct >= 61) {
                            pillClass = "bg-emerald-50 text-emerald-700 border-emerald-200/50";
                          }
                          return (
                            <span className={`inline-block text-[11px] px-2 py-0.5 border rounded-[20px] font-medium ${pillClass}`}>
                              {pct}%
                            </span>
                          );
                        })()
                      ) : (
                        <span className="text-[11px] text-tm-muted">—</span>
                      )}
                    </td>
                  )}

                  {/* Experience Column */}
                  <td className="p-3">
                    <span className="inline-block bg-tm-surface text-[12px] text-tm-text px-2 py-0.5 border border-tm-border rounded-[20px]">
                      {Math.round(cand.years_of_experience)} yrs
                    </span>
                  </td>

                  {/* Action Column */}
                  <td className="p-3 pr-4 text-right">
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
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Drawer Overlay Backdrop */}
      {isDrawerOpen && (
        <div
          onClick={closeDrawer}
          className="fixed inset-0 bg-black/10 z-40 transition-opacity duration-300"
        />
      )}

      {/* Slide-over Drawer */}
      <div
        className={`fixed right-0 top-0 h-full w-[360px] bg-white border-l border-tm-border z-50 flex flex-col justify-between p-6 transition-transform duration-300 ease-out transform ${
          isDrawerOpen ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex-1 flex flex-col gap-4 overflow-y-auto">
          <div className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-tm-muted">
              Candidate Analysis
            </span>
            <h3 className="text-lg font-medium text-tm-text">
              {selectedCandidate?.candidate_id}
            </h3>
            <p className="text-[12px] text-tm-muted">
              {selectedCandidate?.current_title} · {selectedCandidate?.years_of_experience} yrs of experience
            </p>
          </div>

          <div className="border-t border-tm-border pt-4">
            <h4 className="text-[13px] font-medium text-tm-text mb-2">
              Explainable AI (XAI) Reasoning
            </h4>
            <div className="text-[13px] text-tm-text leading-[1.7] whitespace-pre-wrap font-normal">
              {selectedCandidate?.reasoning || "Reasoning detail not available for this candidate. Reasoning summaries are only generated for the top-3 rank tiers."}
            </div>
          </div>
        </div>

        <div className="border-t border-tm-border pt-4 mt-4 shrink-0">
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
