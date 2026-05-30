"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  matchJobDescription,
  triggerDatabaseRecoverySync,
  getStoredCandidatesDirectory,
  RecoverySyncResponse,
  CandidatesDirectoryResponse,
} from "@/lib/api";
import { CandidateMatch, MatchResponse } from "@/types";

// ---------------------------------------------------------------------------
// Recovery sync status shape for the UI badge
// ---------------------------------------------------------------------------

type SyncState =
  | { phase: "idle" }
  | { phase: "syncing" }
  | { phase: "done"; syncResult: RecoverySyncResponse; directory: CandidatesDirectoryResponse }
  | { phase: "error"; message: string };

// ---------------------------------------------------------------------------
// StorageStatusBadge – declared at module level so React never treats it as a
// new component type on parent re-renders (avoids unnecessary unmount/remount).
// ---------------------------------------------------------------------------

function StorageStatusBadge({ syncState }: { syncState: SyncState }) {
  if (syncState.phase === "idle") return null;

  if (syncState.phase === "syncing") {
    return (
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 border border-slate-700 text-xs text-slate-400 font-mono animate-pulse"
        title="Synchronising in-memory vector database with disk storage…"
      >
        <span className="h-2 w-2 rounded-full bg-amber-500 animate-ping" />
        Syncing Storage…
      </div>
    );
  }

  if (syncState.phase === "error") {
    return (
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-rose-950/30 border border-rose-700/40 text-xs text-rose-400 font-mono cursor-default"
        title={`Storage sync failed: ${syncState.message}`}
      >
        <span className="h-2 w-2 rounded-full bg-rose-500" />
        Storage Sync Failed
      </div>
    );
  }

  // phase === "done"
  const { directory, syncResult } = syncState;
  const count = directory.total_stored;
  const isPartial = syncResult.status === "partial" || syncResult.failed > 0;

  return (
    <div
      className={`group flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-mono cursor-default transition-all duration-200 ${
        isPartial
          ? "bg-amber-950/20 border-amber-700/40 text-amber-400 hover:bg-amber-950/30"
          : count === 0
          ? "bg-slate-900 border-slate-700 text-slate-400"
          : "bg-emerald-950/20 border-emerald-700/40 text-emerald-400 hover:bg-emerald-950/30"
      }`}
      title={
        count === 0
          ? "No profiles persisted in disk storage yet."
          : `${syncResult.synced} of ${syncResult.total_found} profile(s) re-indexed into Qdrant. Storage path: ${directory.storage_path}`
      }
    >
      {/* Pulse dot */}
      <span
        className={`h-2 w-2 rounded-full shrink-0 ${
          isPartial
            ? "bg-amber-500"
            : count === 0
            ? "bg-slate-500"
            : "bg-emerald-500"
        }`}
      />

      {/* Label */}
      {count === 0 ? (
        <span>Active Data Directory: Empty</span>
      ) : (
        <span>
          Active Data Directory:&nbsp;
          <span className="font-bold">{count}</span>&nbsp;Verified Candidate
          {count === 1 ? " Profile" : " Profiles"} Loaded
        </span>
      )}

      {/* Partial-failure indicator */}
      {isPartial && (
        <span
          className="ml-1 px-1 py-0.5 rounded bg-amber-700/30 text-amber-300 text-[10px]"
          title={`${syncResult.failed} profile(s) failed to re-index.`}
        >
          {syncResult.failed} err
        </span>
      )}
    </div>
  );
}

export default function AdminDashboard() {
  // -------------------------------------------------------------------------
  // Job-description form state
  // -------------------------------------------------------------------------
  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("");
  const [rawText, setRawText] = useState("");

  // -------------------------------------------------------------------------
  // Matching pipeline UI state
  // -------------------------------------------------------------------------
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matchData, setMatchData] = useState<MatchResponse | null>(null);
  const [selectedCandidate, setSelectedCandidate] =
    useState<CandidateMatch | null>(null);

  // Tab / accordion selection for the XAI detail panel
  const [activeDetailTab, setActiveDetailTab] = useState<
    "all" | "fit" | "gaps" | "prompts"
  >("all");

  // -------------------------------------------------------------------------
  // Storage recovery sync state
  // -------------------------------------------------------------------------
  const [syncState, setSyncState] = useState<SyncState>({ phase: "idle" });

  /**
   * Runs on initial component mount.
   *
   * 1. POSTs to `/profiles/sync-recovery` to heal the in-memory Qdrant index
   *    from the persisted `backend/storage/metadata.json` registry.
   * 2. GETs `/profiles/directory` to populate the storage status badge in the
   *    header with an accurate candidate count.
   *
   * Both calls are fire-and-continue – a failure is captured into `syncState`
   * and shown as a non-blocking error indicator rather than crashing the page.
   */
  const runStartupSync = useCallback(async () => {
    setSyncState({ phase: "syncing" });

    try {
      // Fire sync-recovery first so Qdrant is healed before any user query
      const syncResult = await triggerDatabaseRecoverySync();

      // Then fetch the directory for the badge count
      const directory = await getStoredCandidatesDirectory();

      setSyncState({ phase: "done", syncResult, directory });
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Unknown error during startup sync.";
      setSyncState({ phase: "error", message });
    }
  }, []);

  useEffect(() => {
    runStartupSync();
    // Intentionally run only on the first mount – dep array is stable
  }, [runStartupSync]);

  // -------------------------------------------------------------------------
  // Matching pipeline handlers
  // -------------------------------------------------------------------------

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !rawText.trim()) {
      setError("Position Title and Job Description text are required.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setSelectedCandidate(null);

    try {
      const response = await matchJobDescription({
        title: title.trim(),
        raw_text: rawText.trim(),
        domain: domain.trim() || undefined,
      });
      setMatchData(response);
      if (response.matches && response.matches.length > 0) {
        setSelectedCandidate(response.matches[0]);
      }
    } catch (err) {
      const errMsg =
        err instanceof Error
          ? err.message
          : "Failed to process matching pipeline. Please verify the backend is active.";
      setError(errMsg);
      setMatchData(null);
    } finally {
      setIsLoading(false);
    }
  };

  // -------------------------------------------------------------------------
  // Score display helpers
  // -------------------------------------------------------------------------

  const formatScore = (val: number): string => {
    const scale = val <= 1.0 ? 100 : 1;
    return `${Math.round(val * scale)}`;
  };

  const getScoreColorClass = (scoreStr: string): string => {
    const score = parseInt(scoreStr, 10);
    if (score >= 85) return "text-emerald-400 bg-emerald-500/10 border-emerald-500/30";
    if (score >= 70) return "text-sky-400 bg-sky-500/10 border-sky-500/30";
    if (score >= 50) return "text-amber-400 bg-amber-500/10 border-amber-500/30";
    return "text-rose-400 bg-rose-500/10 border-rose-500/30";
  };

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-fade-in">
      {/* ------------------------------------------------------------------ */}
      {/* Header Banner                                                        */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
            Recruitment Dashboard
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Analyze unstructured job descriptions and match them with
            vector-indexed candidates.
          </p>
        </div>

        {/* Right-side badges row */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 flex-wrap">
          {/* Storage status badge – renders after first sync */}
          <StorageStatusBadge syncState={syncState} />

          {/* Always-visible retrieval active badge */}
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 border border-slate-800 text-xs text-slate-400 font-mono">
            <span className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse" />
            Dual-Space Retrieval Active
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Main Grid: JD Input Form (left) / Results Leaderboard (right)       */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Form Column */}
        <div className="lg:col-span-4 bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md">
          <h2 className="text-lg font-bold text-slate-100 mb-4 flex items-center gap-2">
            <svg
              className="w-5 h-5 text-indigo-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            Job Profile Analyzer
          </h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label
                htmlFor="position-title"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5"
              >
                Position Title
              </label>
              <input
                id="position-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Lead Full-Stack Engineer"
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
                required
              />
            </div>

            <div>
              <label
                htmlFor="position-domain"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5"
              >
                Target Domain (Optional)
              </label>
              <input
                id="position-domain"
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="e.g. FinTech, SaaS, AdTech"
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
              />
            </div>

            <div>
              <label
                htmlFor="job-description"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5"
              >
                Job Description Details
              </label>
              <textarea
                id="job-description"
                rows={10}
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                placeholder="Paste the raw requirements, technologies, must-have skills, and role expectations here..."
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors font-mono resize-none leading-relaxed"
                required
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className={`w-full flex items-center justify-center gap-2 rounded-xl py-3 px-4 font-semibold text-sm transition-all duration-300 shadow-lg ${
                isLoading
                  ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700/50"
                  : "bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-600/25 hover:shadow-indigo-500/35 border border-indigo-500/30 hover:scale-[1.01]"
              }`}
            >
              {isLoading ? (
                <>
                  <svg
                    className="animate-spin h-5 w-5 text-indigo-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  Evaluating Pipeline...
                </>
              ) : (
                <>
                  <svg
                    className="w-5 h-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 9.172V5L8 4z"
                    />
                  </svg>
                  Analyze &amp; Match
                </>
              )}
            </button>
          </form>
        </div>

        {/* Results/Leaderboard Column */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          {error && (
            <div className="bg-rose-950/20 border border-rose-500/30 rounded-2xl p-4 flex items-start gap-3 text-rose-300 text-sm animate-fade-in">
              <svg
                className="w-5 h-5 mt-0.5 text-rose-400 shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <div>
                <span className="font-bold">Evaluation Error:</span> {error}
              </div>
            </div>
          )}

          {/* Matches Leaderboard Section */}
          <div className="bg-slate-955 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md flex-1">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                <svg
                  className="w-5 h-5 text-indigo-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
                  />
                </svg>
                Candidate Match Leaderboard
              </h2>
              {matchData && (
                <span className="text-xs text-slate-500 font-mono">
                  Scored {matchData.total_scored} candidates
                </span>
              )}
            </div>

            {/* Empty State Banner */}
            {!isLoading && !matchData && (
              <div className="h-64 border border-dashed border-slate-800 rounded-xl flex flex-col items-center justify-center text-center p-6 bg-slate-900/10">
                <div className="w-12 h-12 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mb-3">
                  <svg
                    className="w-6 h-6 text-slate-500"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                    />
                  </svg>
                </div>
                <h3 className="font-semibold text-slate-300 text-sm">
                  No Evaluation Data
                </h3>
                <p className="text-slate-500 text-xs mt-1 max-w-sm">
                  The candidate leaderboard is empty. Enter a Position Title and
                  Job Description on the left and run analysis to populate
                  matches.
                </p>
              </div>
            )}

            {/* Loading Skeleton */}
            {isLoading && (
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className="h-14 bg-slate-900/40 border border-slate-800/50 rounded-xl animate-pulse flex items-center justify-between px-4"
                  >
                    <div className="flex items-center gap-3 w-1/3">
                      <div className="w-5 h-5 bg-slate-800 rounded" />
                      <div className="w-24 h-4 bg-slate-800 rounded" />
                    </div>
                    <div className="w-16 h-6 bg-slate-800 rounded-full" />
                    <div className="w-12 h-4 bg-slate-800 rounded" />
                    <div className="w-12 h-4 bg-slate-800 rounded" />
                  </div>
                ))}
              </div>
            )}

            {/* Results Table */}
            {!isLoading &&
              matchData &&
              matchData.matches &&
              matchData.matches.length > 0 && (
                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/10">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-800 text-xs font-semibold uppercase tracking-wider text-slate-500 bg-slate-950/30">
                        <th className="py-3 px-4 text-center">Rank</th>
                        <th className="py-3 px-4">Candidate Profile</th>
                        <th className="py-3 px-4 text-center">
                          Composite Score
                        </th>
                        <th className="py-3 px-4 text-center hidden md:table-cell">
                          Role Fit (40%)
                        </th>
                        <th className="py-3 px-4 text-center hidden md:table-cell">
                          Trajectory (30%)
                        </th>
                        <th className="py-3 px-4 text-center hidden lg:table-cell">
                          Signals (20%)
                        </th>
                        <th className="py-3 px-4 text-center hidden lg:table-cell">
                          Domain (10%)
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {matchData.matches.map((match, index) => {
                        const finalPct = formatScore(match.final_score);
                        const isSelected =
                          selectedCandidate?.candidate_id ===
                          match.candidate_id;

                        return (
                          <tr
                            key={match.candidate_id}
                            onClick={() => setSelectedCandidate(match)}
                            className={`group hover:bg-slate-900/40 cursor-pointer transition-all duration-150 ${
                              isSelected
                                ? "bg-indigo-950/20 border-l-2 border-l-indigo-500"
                                : ""
                            }`}
                          >
                            <td className="py-4 px-4 text-center">
                              <span
                                className={`inline-flex items-center justify-center w-6 h-6 rounded-md font-mono text-xs font-bold ${
                                  index === 0
                                    ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                                    : index === 1
                                    ? "bg-slate-300/20 text-slate-300 border border-slate-300/30"
                                    : index === 2
                                    ? "bg-amber-800/20 text-amber-600 border border-amber-800/30"
                                    : "text-slate-500"
                                }`}
                              >
                                {index + 1}
                              </span>
                            </td>
                            <td className="py-4 px-4">
                              <div>
                                <div className="font-semibold text-slate-200 group-hover:text-white transition-colors">
                                  {match.name || "Unknown"}
                                </div>
                                <div className="text-xs text-slate-500 font-mono mt-0.5">
                                  {match.candidate_id}
                                </div>
                              </div>
                            </td>
                            <td className="py-4 px-4 text-center">
                              <span
                                className={`inline-block font-bold text-sm px-2.5 py-1 rounded-full border ${getScoreColorClass(finalPct)}`}
                              >
                                {finalPct}%
                              </span>
                            </td>
                            <td className="py-4 px-4 text-center hidden md:table-cell text-slate-300 text-sm font-mono">
                              {formatScore(match.role_fit_score)}%
                            </td>
                            <td className="py-4 px-4 text-center hidden md:table-cell text-slate-300 text-sm font-mono">
                              {formatScore(match.trajectory_score)}%
                            </td>
                            <td className="py-4 px-4 text-center hidden lg:table-cell text-slate-300 text-sm font-mono">
                              {formatScore(match.platform_signals_score)}%
                            </td>
                            <td className="py-4 px-4 text-center hidden lg:table-cell text-slate-300 text-sm font-mono">
                              {formatScore(match.domain_alignment_score)}%
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Accordion / Detailed XAI Analysis Panel                             */}
      {/* ------------------------------------------------------------------ */}
      <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-4 mb-6">
          <div>
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <svg
                className="w-5 h-5 text-indigo-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
              Explainable AI (XAI) Fit Summary
            </h2>
            {selectedCandidate && (
              <p className="text-slate-400 text-xs mt-0.5">
                Inspect AI breakdown analysis for candidate{" "}
                <span className="font-mono text-indigo-400 font-bold">
                  {selectedCandidate.name}
                </span>{" "}
                ({selectedCandidate.candidate_id})
              </p>
            )}
          </div>

          {selectedCandidate && (
            <div className="flex bg-slate-900 border border-slate-800 rounded-lg p-0.5 text-xs">
              <button
                onClick={() => setActiveDetailTab("all")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  activeDetailTab === "all"
                    ? "bg-indigo-600 text-white font-semibold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                All Insights
              </button>
              <button
                onClick={() => setActiveDetailTab("fit")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  activeDetailTab === "fit"
                    ? "bg-indigo-600 text-white font-semibold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                🟢 Alignment
              </button>
              <button
                onClick={() => setActiveDetailTab("gaps")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  activeDetailTab === "gaps"
                    ? "bg-indigo-600 text-white font-semibold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                🔴 Gaps
              </button>
              <button
                onClick={() => setActiveDetailTab("prompts")}
                className={`px-3 py-1 rounded-md transition-colors ${
                  activeDetailTab === "prompts"
                    ? "bg-indigo-600 text-white font-semibold"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                🎤 Prompts
              </button>
            </div>
          )}
        </div>

        {/* Detail cards */}
        {!selectedCandidate ? (
          <div className="h-32 border border-dashed border-slate-800 rounded-xl flex items-center justify-center text-center p-4 bg-slate-900/10">
            <p className="text-slate-500 text-xs max-w-sm">
              Please analyze a job description and select a candidate from the
              table above to view deep fit alignment metrics and screening
              guides.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-fade-in">
            {/* Strongest Alignment */}
            {(activeDetailTab === "all" || activeDetailTab === "fit") && (
              <div className="flex flex-col bg-emerald-950/20 border border-emerald-800/30 rounded-xl p-5 shadow-lg relative overflow-hidden group">
                <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity duration-300">
                  <span className="text-7xl">🟢</span>
                </div>
                <h3 className="text-emerald-400 text-sm font-bold uppercase tracking-wider flex items-center gap-2 mb-3">
                  <span className="text-base">🟢</span> Strongest Alignment
                </h3>
                <p className="text-emerald-300/90 text-sm leading-relaxed whitespace-pre-line flex-1 bg-slate-900/30 border border-emerald-950/30 rounded-lg p-3">
                  {selectedCandidate.strongest_alignment ||
                    "No explicit alignment indicators generated."}
                </p>
              </div>
            )}

            {/* Competency Gaps */}
            {(activeDetailTab === "all" || activeDetailTab === "gaps") && (
              <div className="flex flex-col bg-amber-950/20 border border-amber-800/30 rounded-xl p-5 shadow-lg relative overflow-hidden group">
                <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity duration-300">
                  <span className="text-7xl">🔴</span>
                </div>
                <h3 className="text-amber-400 text-sm font-bold uppercase tracking-wider flex items-center gap-2 mb-3">
                  <span className="text-base">🔴</span> Competency Gaps
                </h3>
                <p className="text-amber-300/90 text-sm leading-relaxed whitespace-pre-line flex-1 bg-slate-900/30 border border-amber-950/30 rounded-lg p-3">
                  {selectedCandidate.competency_gaps ||
                    "No severe gaps flagged for this profile."}
                </p>
              </div>
            )}

            {/* Screening Prompts */}
            {(activeDetailTab === "all" || activeDetailTab === "prompts") && (
              <div className="flex flex-col bg-indigo-950/20 border border-indigo-800/30 rounded-xl p-5 shadow-lg relative overflow-hidden group md:col-span-1">
                <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity duration-300">
                  <span className="text-7xl">🎤</span>
                </div>
                <h3 className="text-indigo-400 text-sm font-bold uppercase tracking-wider flex items-center gap-2 mb-3">
                  <span className="text-base">🎤</span> Screening Prompts
                </h3>
                <div className="space-y-2.5 flex-1 flex flex-col justify-between">
                  <div className="space-y-2 bg-slate-900/40 rounded-lg p-3 border border-indigo-950/30 overflow-y-auto max-h-52 font-mono text-xs text-indigo-300/90 leading-relaxed scrollbar-thin">
                    {selectedCandidate.tailored_interview_prompts &&
                    selectedCandidate.tailored_interview_prompts.length > 0 ? (
                      selectedCandidate.tailored_interview_prompts.map(
                        (promptText, i) => (
                          <div
                            key={i}
                            className="p-2 border-b border-indigo-900/20 last:border-b-0 flex gap-2"
                          >
                            <span className="text-indigo-500 font-bold shrink-0">
                              {i + 1}.
                            </span>
                            <span className="select-all">{promptText}</span>
                          </div>
                        )
                      )
                    ) : (
                      <span className="text-slate-500 italic">
                        No tailored screening prompts provided.
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
