"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  matchJobDescription,
  triggerDatabaseRecoverySync,
  getStoredCandidatesDirectory,
  RecoverySyncResponse,
  CandidatesDirectoryResponse,
  loginAdmin,
  StoredCandidateSummary,
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
// StorageStatusBadge – Light Notion/Stripe style
// ---------------------------------------------------------------------------

function StorageStatusBadge({ syncState }: { syncState: SyncState }) {
  if (syncState.phase === "idle") return null;

  if (syncState.phase === "syncing") {
    return (
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-tm-surface border border-tm-border text-[11px] text-tm-muted font-mono"
        title="Synchronising in-memory vector database with disk storage…"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
        Syncing Storage…
      </div>
    );
  }

  if (syncState.phase === "error") {
    return (
      <div
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-rose-50 border border-rose-100 text-[11px] text-rose-600 font-mono cursor-default"
        title={`Storage sync failed: ${syncState.message}`}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
        Sync Failed
      </div>
    );
  }

  const { directory, syncResult } = syncState;
  const count = directory.total_stored;
  const isPartial = syncResult.status === "partial" || syncResult.failed > 0;

  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-mono cursor-default transition-colors ${
        isPartial
          ? "bg-amber-50 border-amber-200 text-amber-700"
          : count === 0
          ? "bg-tm-surface border-tm-border text-tm-muted"
          : "bg-emerald-50 border-emerald-100 text-emerald-700"
      }`}
      title={
        count === 0
          ? "No profiles persisted in disk storage yet."
          : `${syncResult.synced} of ${syncResult.total_found} profile(s) re-indexed. Storage path: ${directory.storage_path}`
      }
    >
      <span
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          isPartial
            ? "bg-amber-500"
            : count === 0
            ? "bg-neutral-400"
            : "bg-tm-success"
        }`}
      />
      {count === 0 ? (
        <span>Directory: Empty</span>
      ) : (
        <span>
          Directory: <span className="font-medium">{count}</span> Loaded
        </span>
      )}
      {isPartial && (
        <span className="ml-1 px-1 py-0.2 bg-amber-200 text-amber-800 text-[9px] rounded">
          {syncResult.failed} err
        </span>
      )}
    </div>
  );
}

export default function AdminDashboard() {
  const [token, setToken] = useState<string | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [adminTab, setAdminTab] = useState<"matching" | "directory">("matching");
  const [directoryData, setDirectoryData] = useState<CandidatesDirectoryResponse | null>(null);
  const [selectedDirectoryCandidate, setSelectedDirectoryCandidate] = useState<StoredCandidateSummary | null>(null);

  const [title, setTitle] = useState("");
  const [domain, setDomain] = useState("");
  const [rawText, setRawText] = useState("");

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matchData, setMatchData] = useState<MatchResponse | null>(null);
  const [selectedCandidate, setSelectedCandidate] = useState<CandidateMatch | null>(null);

  const [activeDetailTab, setActiveDetailTab] = useState<"all" | "fit" | "gaps" | "prompts">("all");
  const [syncState, setSyncState] = useState<SyncState>({ phase: "idle" });

  useEffect(() => {
    const storedToken = localStorage.getItem("token");
    setToken(storedToken);
    setIsInitialized(true);
  }, []);

  const runStartupSync = useCallback(async () => {
    setSyncState({ phase: "syncing" });

    try {
      const syncResult = await triggerDatabaseRecoverySync();
      const directory = await getStoredCandidatesDirectory();
      setSyncState({ phase: "done", syncResult, directory });
      setDirectoryData(directory);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error during sync.";
      setSyncState({ phase: "error", message });

      if (
        message.includes("401") ||
        message.includes("Unauthorized") ||
        message.includes("forbidden") ||
        message.includes("ExpiredSignatureError") ||
        message.toLowerCase().includes("token")
      ) {
        localStorage.removeItem("token");
        setToken(null);
      }
    }
  }, []);

  useEffect(() => {
    if (token) {
      runStartupSync();
    }
  }, [token, runStartupSync]);

  const refreshDirectory = useCallback(async () => {
    try {
      const directory = await getStoredCandidatesDirectory();
      setDirectoryData(directory);
      setSyncState((prev) => {
        if (prev.phase === "done") {
          return { ...prev, directory };
        }
        return prev;
      });
    } catch (err) {
      console.error("Failed to refresh candidates directory:", err);
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !rawText.trim()) {
      setError("Position Title and Job Description text are required.");
      return;
    }

    setIsLoading(true);
    setError(null);
    setSelectedCandidate(null);
    setSelectedDirectoryCandidate(null);

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
      const errMsg = err instanceof Error ? err.message : "Failed to process matching pipeline.";
      setError(errMsg);
      setMatchData(null);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setLoginError(null);
    try {
      const response = await loginAdmin(password);
      localStorage.setItem("token", response.token);
      setToken(response.token);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Failed to authenticate. Access denied.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    setToken(null);
    setMatchData(null);
    setSelectedCandidate(null);
    setSelectedDirectoryCandidate(null);
    setDirectoryData(null);
    setSyncState({ phase: "idle" });
  };

  const formatScore = (val: number): string => {
    const scale = val <= 1.0 ? 100 : 1;
    return `${Math.round(val * scale)}`;
  };

  const getScoreColorClass = (scoreStr: string): string => {
    const score = parseInt(scoreStr, 10);
    if (score >= 85) return "text-emerald-700 bg-emerald-50 border-emerald-100";
    if (score >= 70) return "text-sky-700 bg-sky-50 border-sky-100";
    if (score >= 50) return "text-amber-700 bg-amber-50 border-amber-150";
    return "text-rose-700 bg-rose-50 border-rose-100";
  };

  if (!isInitialized) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <i className="ti ti-loader text-lg text-tm-muted animate-spin" />
      </div>
    );
  }

  if (!token) {
    return (
      <div className="min-h-screen bg-tm-surface flex items-center justify-center p-4">
        <div className="w-full max-w-sm bg-white border border-tm-border rounded-[12px] p-6">
          <div className="text-center space-y-2 mb-6">
            <div className="inline-flex items-center justify-center w-10 h-10 rounded-[8px] bg-tm-surface border border-tm-border text-tm-text">
              <i className="ti ti-lock text-lg" />
            </div>
            <h1 className="text-base font-medium text-tm-text">
              Access Restricted
            </h1>
            <p className="text-tm-muted text-xs">
              Administrative credentials are required to view candidate records.
            </p>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label
                htmlFor="admin-password"
                className="block text-xs text-tm-muted mb-1 font-medium"
              >
                Administrative Passphrase
              </label>
              <input
                id="admin-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter passphrase"
                className="w-full bg-white border border-tm-border rounded-[8px] px-3 py-2 text-xs text-tm-text placeholder-gray-400 focus:outline-none focus:border-tm-accent"
                required
              />
            </div>

            {loginError && (
              <div className="bg-rose-50 border border-rose-100 rounded-[8px] p-2.5 text-rose-700 text-xs font-medium">
                {loginError}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full flex items-center justify-center gap-1.5 rounded-[8px] py-2 px-3 text-xs bg-tm-accent hover:bg-neutral-800 text-white font-medium transition-colors"
            >
              {isSubmitting ? (
                <i className="ti ti-loader text-sm animate-spin" />
              ) : (
                "Authorize Access"
              )}
            </button>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-tm-border pb-5">
        <div>
          <h1 className="text-xl font-medium text-tm-text">
            Recruitment Dashboard
          </h1>
          <p className="text-tm-muted text-xs mt-1">
            Analyze unstructured job descriptions and match them with MongoDB cloud-indexed candidates.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap text-xs">
          <StorageStatusBadge syncState={syncState} />

          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-tm-surface border border-tm-border text-[11px] text-tm-muted font-mono">
            <span className="w-1.5 h-1.5 rounded-full bg-tm-accent" />
            Dual-Space Retrieval Active
          </div>

          <button
            onClick={handleLogout}
            className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-white hover:bg-tm-surface border border-tm-border text-[11px] text-tm-muted hover:text-tm-text transition-colors"
          >
            <i className="ti ti-logout text-xs" />
            Log Out
          </button>
        </div>
      </div>

      {/* Main Grid: JD Input Form (left) / Results Leaderboard (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Form Column */}
        <div className="lg:col-span-4 bg-white border border-tm-border rounded-[12px] p-5">
          <h2 className="text-sm font-medium text-tm-text mb-4 flex items-center gap-1.5">
            <i className="ti ti-file-text text-base text-tm-text" />
            Job Profile Analyzer
          </h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="position-title"
                className="block text-xs font-medium text-tm-muted mb-1"
              >
                Position Title
              </label>
              <input
                id="position-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Lead Full-Stack Engineer"
                className="w-full bg-white border border-tm-border rounded-[8px] px-3 py-2 text-xs text-tm-text placeholder-gray-400 focus:outline-none focus:border-tm-accent"
                required
              />
            </div>

            <div>
              <label
                htmlFor="position-domain"
                className="block text-xs font-medium text-tm-muted mb-1"
              >
                Target Domain (Optional)
              </label>
              <input
                id="position-domain"
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="e.g. FinTech, SaaS"
                className="w-full bg-white border border-tm-border rounded-[8px] px-3 py-2 text-xs text-tm-text placeholder-gray-400 focus:outline-none focus:border-tm-accent"
              />
            </div>

            <div>
              <label
                htmlFor="job-description"
                className="block text-xs font-medium text-tm-muted mb-1"
              >
                Job Description Details
              </label>
              <textarea
                id="job-description"
                rows={9}
                value={rawText}
                onChange={(e) => setRawText(e.target.value)}
                placeholder="Paste requirements and expectations here..."
                className="w-full bg-white border border-tm-border rounded-[8px] px-3 py-2.5 text-xs text-tm-text placeholder-gray-400 focus:outline-none focus:border-tm-accent font-mono resize-none leading-relaxed"
                required
              />
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className={`w-full flex items-center justify-center gap-1.5 rounded-[8px] py-2 px-3 text-xs font-medium transition-colors ${
                isLoading
                  ? "bg-tm-surface text-tm-muted cursor-not-allowed border border-tm-border"
                  : "bg-tm-accent hover:bg-neutral-800 text-white border border-transparent"
              }`}
            >
              {isLoading ? (
                <>
                  <i className="ti ti-loader text-sm animate-spin" />
                  Evaluating Pipeline...
                </>
              ) : (
                <>
                  <i className="ti ti-cpu text-sm" />
                  Analyze &amp; Match
                </>
              )}
            </button>
          </form>
        </div>

        {/* Results/Leaderboard & Directory Columns */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          {error && (
            <div className="bg-rose-50 border border-rose-100 rounded-[12px] p-4 flex items-start gap-2.5 text-rose-700 text-xs font-medium">
              <i className="ti ti-alert-triangle text-sm shrink-0" />
              <div>
                <span className="font-medium">Evaluation Error:</span> {error}
              </div>
            </div>
          )}

          {/* Tabbed Leaderboard & Directory Section */}
          <div className="bg-white border border-tm-border rounded-[12px] p-5 flex-1 flex flex-col">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-tm-border pb-3 mb-4">
              <div className="flex bg-tm-surface border border-tm-border rounded-[8px] p-0.5 text-xs font-medium">
                <button
                  onClick={() => setAdminTab("matching")}
                  className={`px-3 py-1.5 rounded-[6px] transition-colors ${
                    adminTab === "matching"
                      ? "bg-white text-tm-text border border-tm-border font-medium"
                      : "text-tm-muted hover:text-tm-text border border-transparent"
                  }`}
                >
                  Job Match Leaderboard
                </button>
                <button
                  onClick={() => {
                    setAdminTab("directory");
                    refreshDirectory();
                  }}
                  className={`px-3 py-1.5 rounded-[6px] transition-colors ${
                    adminTab === "directory"
                      ? "bg-white text-tm-text border border-tm-border font-medium"
                      : "text-tm-muted hover:text-tm-text border border-transparent"
                  }`}
                >
                  Public Submissions
                </button>
              </div>

              {adminTab === "matching" ? (
                matchData && (
                  <span className="text-xs text-tm-muted font-mono">
                    Scored {matchData.total_scored} candidates
                  </span>
                )
              ) : (
                directoryData && (
                  <span className="text-xs text-tm-muted font-mono">
                    Total: {directoryData.total_stored} profiles
                  </span>
                )
              )}
            </div>

            {/* TAB 1: MATCHING LEADERBOARD */}
            {adminTab === "matching" && (
              <div className="flex-1 flex flex-col justify-between">
                {/* Empty State Banner */}
                {!isLoading && !matchData && (
                  <div className="h-64 border border-dashed border-tm-border rounded-[8px] flex flex-col items-center justify-center text-center p-6 bg-tm-surface">
                    <div className="w-9 h-9 rounded-full bg-white border border-tm-border flex items-center justify-center mb-3">
                      <i className="ti ti-search text-base text-tm-muted" />
                    </div>
                    <h3 className="font-medium text-tm-text text-xs">
                      No Evaluation Data
                    </h3>
                    <p className="text-tm-muted text-xs mt-1 max-w-xs leading-relaxed">
                      The candidate leaderboard is empty. Enter a Position Title and Job Description on the left and run analysis to populate matches.
                    </p>
                  </div>
                )}

                {/* Loading Skeleton */}
                {isLoading && (
                  <div className="space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div
                        key={i}
                        className="h-12 bg-tm-surface border border-tm-border rounded-[8px] animate-pulse flex items-center justify-between px-3"
                      >
                        <div className="flex items-center gap-3 w-1/3">
                          <div className="w-4 h-4 bg-gray-200 rounded" />
                          <div className="w-20 h-3 bg-gray-200 rounded" />
                        </div>
                        <div className="w-12 h-5 bg-gray-200 rounded-full" />
                        <div className="w-10 h-3 bg-gray-200 rounded" />
                        <div className="w-10 h-3 bg-gray-200 rounded" />
                      </div>
                    ))}
                  </div>
                )}

                {/* Results Table */}
                {!isLoading &&
                  matchData &&
                  matchData.matches &&
                  matchData.matches.length > 0 && (
                    <div className="overflow-x-auto rounded-[8px] border border-tm-border bg-white">
                      <table className="w-full text-left border-collapse">
                        <thead>
                          <tr className="border-b border-tm-border text-[11px] font-medium uppercase tracking-wider text-tm-muted bg-tm-surface">
                            <th className="py-2.5 px-3 text-center w-12">Rank</th>
                            <th className="py-2.5 px-3">Candidate Profile</th>
                            <th className="py-2.5 px-3 text-center">Score</th>
                            <th className="py-2.5 px-3 text-center hidden md:table-cell">Role Fit</th>
                            <th className="py-2.5 px-3 text-center hidden md:table-cell">Trajectory</th>
                            <th className="py-2.5 px-3 text-center hidden lg:table-cell">Signals</th>
                            <th className="py-2.5 px-3 text-center hidden lg:table-cell">Domain</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-tm-border/60">
                          {matchData.matches.map((match, index) => {
                            const finalPct = formatScore(match.final_score);
                            const isSelected = selectedCandidate?.candidate_id === match.candidate_id;

                            return (
                              <tr
                                key={match.candidate_id}
                                onClick={() => {
                                  setSelectedCandidate(match);
                                  setSelectedDirectoryCandidate(null);
                                }}
                                className={`group hover:bg-tm-surface/65 cursor-pointer transition-colors ${
                                  isSelected ? "bg-tm-surface font-medium" : ""
                                }`}
                              >
                                <td className="py-3 px-3 text-center">
                                  <span
                                    className={`inline-flex items-center justify-center w-5 h-5 rounded font-mono text-[11px] font-medium ${
                                      index === 0
                                        ? "bg-amber-50 text-amber-700 border border-amber-100"
                                        : index === 1
                                        ? "bg-gray-100 text-gray-700 border border-gray-200"
                                        : index === 2
                                        ? "bg-amber-50/50 text-amber-600 border border-amber-100/50"
                                        : "text-tm-muted"
                                    }`}
                                  >
                                    {index + 1}
                                  </span>
                                </td>
                                <td className="py-3 px-3">
                                  <div>
                                    <div className="text-xs text-tm-text group-hover:text-tm-accent transition-colors font-medium">
                                      {match.name || "Unknown"}
                                    </div>
                                    <div className="text-[10px] text-tm-muted font-mono">
                                      {match.candidate_id}
                                    </div>
                                  </div>
                                </td>
                                <td className="py-3 px-3 text-center">
                                  <span
                                    className={`inline-block text-[11px] px-2 py-0.5 rounded-full border font-mono font-medium ${getScoreColorClass(finalPct)}`}
                                  >
                                    {finalPct}%
                                  </span>
                                </td>
                                <td className="py-3 px-3 text-center hidden md:table-cell text-tm-text text-xs font-mono">
                                  {formatScore(match.role_fit_score)}%
                                </td>
                                <td className="py-3 px-3 text-center hidden md:table-cell text-tm-text text-xs font-mono">
                                  {formatScore(match.trajectory_score)}%
                                </td>
                                <td className="py-3 px-3 text-center hidden lg:table-cell text-tm-text text-xs font-mono">
                                  {formatScore(match.platform_signals_score)}%
                                </td>
                                <td className="py-3 px-3 text-center hidden lg:table-cell text-tm-text text-xs font-mono">
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
            )}

            {/* TAB 2: PUBLIC SUBMISSIONS DIRECTORY */}
            {adminTab === "directory" && (
              <div className="flex-1 flex flex-col justify-between">
                {!directoryData || directoryData.candidates.length === 0 ? (
                  <div className="h-64 border border-dashed border-tm-border rounded-[8px] flex flex-col items-center justify-center text-center p-6 bg-tm-surface">
                    <div className="w-9 h-9 rounded-full bg-white border border-tm-border flex items-center justify-center mb-3">
                      <i className="ti ti-archive text-base text-tm-muted" />
                    </div>
                    <h3 className="font-medium text-tm-text text-xs">
                      No Registered Profiles
                    </h3>
                    <p className="text-tm-muted text-xs mt-1 max-w-xs leading-relaxed">
                      MongoDB cloud directory returned 0 candidate profiles. Upload resumes in the Candidate Ingestion portal to register candidates.
                    </p>
                  </div>
                ) : (
                  <div className="overflow-x-auto rounded-[8px] border border-tm-border bg-white">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="border-b border-tm-border text-[11px] font-medium uppercase tracking-wider text-tm-muted bg-tm-surface">
                          <th className="py-2.5 px-3">Candidate Profile</th>
                          <th className="py-2.5 px-3 text-center">Ingestion Date</th>
                          <th className="py-2.5 px-3 text-center">Repository</th>
                          <th className="py-2.5 px-3 text-right">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-tm-border/60">
                        {directoryData.candidates.map((candidate) => {
                          const isSelected = selectedDirectoryCandidate?.candidate_id === candidate.candidate_id;
                          const formattedDate = candidate.stored_at
                            ? new Date(candidate.stored_at).toLocaleDateString(undefined, {
                                year: "numeric",
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })
                            : "Unknown";

                          return (
                            <tr
                              key={candidate.candidate_id}
                              onClick={() => {
                                setSelectedDirectoryCandidate(candidate);
                                setSelectedCandidate({
                                  candidate_id: candidate.candidate_id,
                                  name: candidate.name,
                                  rrf_score: 0,
                                  final_score: 0,
                                  role_fit_score: 0,
                                  trajectory_score: 0,
                                  platform_signals_score: 0,
                                  domain_alignment_score: 0,
                                  strongest_alignment: `This candidate profile was retrieved from the secure MongoDB cloud storage directory.\n\nFile Path: ${candidate.profile_path || "N/A"}`,
                                  competency_gaps: "To analyze candidate-to-role matching diagnostics, configure a Job Profile on the left, then click 'Analyze & Match'.",
                                  tailored_interview_prompts: [
                                    `Verify credentials for candidate ${candidate.name} (${candidate.candidate_id}).`,
                                  ]
                                });
                              }}
                              className={`group hover:bg-tm-surface/65 cursor-pointer transition-colors ${
                                isSelected ? "bg-tm-surface font-medium" : ""
                              }`}
                            >
                              <td className="py-3 px-3">
                                <div>
                                  <div className="text-xs text-tm-text group-hover:text-tm-accent transition-colors font-medium">
                                    {candidate.name || "Unknown"}
                                  </div>
                                  <div className="text-[10px] text-tm-muted font-mono">
                                    {candidate.candidate_id}
                                  </div>
                                </div>
                              </td>
                              <td className="py-3 px-3 text-center text-tm-muted text-xs font-mono">
                                {formattedDate}
                              </td>
                              <td className="py-3 px-3 text-center">
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-[4px] bg-tm-surface border border-tm-border text-[10px] text-tm-muted font-mono">
                                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                                  MongoDB Cloud
                                </span>
                              </td>
                              <td className="py-3 px-3 text-right">
                                <button className="text-tm-muted group-hover:text-tm-accent text-xs font-medium underline decoration-dotted transition-colors">
                                  View Diagnostics
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Accordion / Detailed XAI Analysis Panel */}
      <div className="bg-white border border-tm-border rounded-[12px] p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-tm-border pb-3 mb-4">
          <div>
            <h2 className="text-sm font-medium text-tm-text flex items-center gap-1.5">
              <i className="ti ti-sparkles text-base text-tm-text animate-pulse" />
              Explainable AI (XAI) Fit Summary
            </h2>
            {selectedCandidate && (
              <p className="text-tm-muted text-xs mt-0.5">
                Inspect AI breakdown analysis for candidate{" "}
                <span className="font-mono text-tm-text font-medium">
                  {selectedCandidate.name}
                </span>{" "}
                ({selectedCandidate.candidate_id})
              </p>
            )}
          </div>

          {selectedCandidate && (
            <div className="flex bg-tm-surface border border-tm-border rounded-[8px] p-0.5 text-xs font-medium">
              <button
                onClick={() => setActiveDetailTab("all")}
                className={`px-3 py-1 rounded-[6px] transition-colors ${
                  activeDetailTab === "all"
                    ? "bg-white text-tm-text border border-tm-border"
                    : "text-tm-muted hover:text-tm-text border border-transparent"
                }`}
              >
                All Insights
              </button>
              <button
                onClick={() => setActiveDetailTab("fit")}
                className={`px-3 py-1 rounded-[6px] transition-colors ${
                  activeDetailTab === "fit"
                    ? "bg-white text-emerald-700 border border-tm-border"
                    : "text-tm-muted hover:text-emerald-600 border border-transparent"
                }`}
              >
                Alignment
              </button>
              <button
                onClick={() => setActiveDetailTab("gaps")}
                className={`px-3 py-1 rounded-[6px] transition-colors ${
                  activeDetailTab === "gaps"
                    ? "bg-white text-amber-700 border border-tm-border"
                    : "text-tm-muted hover:text-amber-600 border border-transparent"
                }`}
              >
                Gaps
              </button>
              <button
                onClick={() => setActiveDetailTab("prompts")}
                className={`px-3 py-1 rounded-[6px] transition-colors ${
                  activeDetailTab === "prompts"
                    ? "bg-white text-indigo-700 border border-tm-border"
                    : "text-tm-muted hover:text-indigo-600 border border-transparent"
                }`}
              >
                Prompts
              </button>
            </div>
          )}
        </div>

        {/* Detail cards */}
        {!selectedCandidate ? (
          <div className="h-24 border border-dashed border-tm-border rounded-[8px] flex items-center justify-center text-center p-4 bg-tm-surface">
            <p className="text-tm-muted text-xs max-w-sm">
              Please select a candidate from either the Match Leaderboard or Public Submissions to view deep fit alignment metrics and screening guides.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Strongest Alignment */}
            {(activeDetailTab === "all" || activeDetailTab === "fit") && (
              <div className="flex flex-col bg-emerald-50/10 border border-emerald-100 rounded-[8px] p-4">
                <h3 className="text-emerald-700 text-xs font-medium uppercase tracking-wider flex items-center gap-1.5 mb-2">
                  <i className="ti ti-circle-check text-sm" /> Strongest Alignment
                </h3>
                <p className="text-emerald-800/95 text-xs leading-relaxed whitespace-pre-line flex-1 bg-white border border-emerald-100/60 rounded-[8px] p-3">
                  {selectedCandidate.strongest_alignment || "No explicit alignment indicators generated."}
                </p>
              </div>
            )}

            {/* Competency Gaps */}
            {(activeDetailTab === "all" || activeDetailTab === "gaps") && (
              <div className="flex flex-col bg-amber-50/10 border border-amber-100/80 rounded-[8px] p-4">
                <h3 className="text-amber-700 text-xs font-medium uppercase tracking-wider flex items-center gap-1.5 mb-2">
                  <i className="ti ti-circle-x text-sm" /> Competency Gaps
                </h3>
                <p className="text-amber-800/95 text-xs leading-relaxed whitespace-pre-line flex-1 bg-white border border-amber-150 rounded-[8px] p-3">
                  {selectedCandidate.competency_gaps || "No severe gaps flagged for this profile."}
                </p>
              </div>
            )}

            {/* Screening Prompts */}
            {(activeDetailTab === "all" || activeDetailTab === "prompts") && (
              <div className="flex flex-col bg-indigo-50/10 border border-indigo-100 rounded-[8px] p-4 md:col-span-1">
                <h3 className="text-indigo-700 text-xs font-medium uppercase tracking-wider flex items-center gap-1.5 mb-2">
                  <i className="ti ti-messages text-sm" /> Screening Prompts
                </h3>
                <div className="space-y-2.5 flex-1 flex flex-col justify-between">
                  <div className="space-y-2 bg-white rounded-[8px] p-3 border border-indigo-100 overflow-y-auto max-h-52 font-mono text-[11px] text-indigo-900/90 leading-relaxed scrollbar-thin">
                    {selectedCandidate.tailored_interview_prompts &&
                    selectedCandidate.tailored_interview_prompts.length > 0 ? (
                      selectedCandidate.tailored_interview_prompts.map((promptText, i) => (
                        <div
                          key={i}
                          className="py-1.5 border-b border-indigo-50/65 last:border-b-0 flex gap-1.5"
                        >
                          <span className="text-indigo-500 font-medium shrink-0">
                            {i + 1}.
                          </span>
                          <span className="select-all">{promptText}</span>
                        </div>
                      ))
                    ) : (
                      <span className="text-tm-muted italic">
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
