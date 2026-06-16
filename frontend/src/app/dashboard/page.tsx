"use client";

import React, { useState, useEffect, useCallback } from "react";
import MetricsRow, { MetricCardData } from "@/components/MetricsRow";
import PipelineProgress from "@/components/PipelineProgress";
import Leaderboard, { Candidate } from "@/components/Leaderboard";
import JDPanel from "@/components/JDPanel";
import UploadPanel from "@/components/UploadPanel";
import { loginAdmin } from "@/lib/api";

interface JobRunData {
  job_id: string;
  run_at: string;
  total_scored: number;
  runtime_seconds: number;
  candidates: Candidate[];
}

export default function DashboardPage() {
  const [token, setToken] = useState<string | null>(null);
  const [isInitialized, setIsInitialized] = useState<boolean>(false);
  
  // Auth Form
  const [password, setPassword] = useState<string>("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginLoading, setLoginLoading] = useState<boolean>(false);

  // Active Job Pipeline States
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  // Current Dashboard Data
  const [runData, setRunData] = useState<JobRunData | null>(null);
  const [loadingLatest, setLoadingLatest] = useState<boolean>(false);

  // JD Relevance States
  const [jdActive, setJdActive] = useState<boolean>(false);
  const [jdTokenCount, setJdTokenCount] = useState<number>(0);

  // Initialize Auth
  useEffect(() => {
    const storedToken = localStorage.getItem("token");
    setToken(storedToken);
    setIsInitialized(true);
  }, []);

  // Fetch results for a job
  const fetchJobResults = useCallback(async (jobId: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/v1/results/${jobId}`);
      if (res.ok) {
        const data: JobRunData = await res.json();
        setRunData(data);
      }
    } catch (err) {
      console.error("Failed to fetch results for job", jobId, err);
    }
  }, []);

  // Fetch latest run results
  const fetchLatestResults = useCallback(async () => {
    setLoadingLatest(true);
    try {
      const res = await fetch("http://localhost:8000/api/v1/results/latest");
      if (res.ok) {
        const data: JobRunData = await res.json();
        setRunData(data);
      } else {
        setRunData(null);
      }
    } catch (err) {
      console.error("Failed to fetch latest results", err);
      setRunData(null);
    } finally {
      setLoadingLatest(false);
    }
  }, []);

  // Fetch latest result on login
  useEffect(() => {
    if (token) {
      fetchLatestResults();
    }
  }, [token, fetchLatestResults]);

  // Auth Handler
  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginLoading(true);
    setLoginError(null);
    try {
      const response = await loginAdmin(password);
      localStorage.setItem("token", response.token);
      setToken(response.token);
    } catch (err) {
      setLoginError(
        err instanceof Error ? err.message : "Failed to authenticate. Access denied."
      );
    } finally {
      setLoginLoading(false);
    }
  };

  // Upload Panel Handler
  const handleUploadSuccess = (jobId: string, taskId: string) => {
    setIsModalOpen(false);
    setActiveJobId(jobId);
    setActiveTaskId(taskId);
    setRunData(null); // Clear previous results to show progress bar
  };

  // Pipeline SSE Complete Handler
  const handlePipelineComplete = () => {
    if (activeJobId) {
      // Auto-fetch results
      fetchJobResults(activeJobId);
    }
  };

  // JD Panel Rerank Handler
  const handleRerankSuccess = (
    newCandidates: Candidate[],
    active: boolean,
    tokenCount: number
  ) => {
    setJdActive(active);
    setJdTokenCount(tokenCount);
    if (runData) {
      setRunData({
        ...runData,
        candidates: newCandidates,
      });
    }
  };

  if (!isInitialized) {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-white">
        <div className="animate-spin h-5 w-5 text-tm-accent border-2 border-tm-accent border-t-transparent rounded-full" />
      </div>
    );
  }

  // Stripe-like Clean Login Screen
  if (!token) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center p-4 select-none">
        <div className="w-full max-w-sm border border-tm-border rounded-[12px] p-6 bg-white flex flex-col gap-6">
          <div className="flex flex-col gap-1.5 text-center">
            <span className="text-[11px] uppercase tracking-wider text-tm-muted">
              Security Verification
            </span>
            <h1 className="text-lg font-medium text-tm-text">
              Recruiter Dashboard Access
            </h1>
            <p className="text-[12px] text-tm-muted">
              Enter your administrative passphrase to view placements.
            </p>
          </div>

          <form onSubmit={handleLoginSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="passphrase" className="text-[11px] font-medium text-tm-muted uppercase">
                Passphrase
              </label>
              <input
                id="passphrase"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full border border-tm-border rounded-[8px] px-3 py-2 text-sm focus:outline-none focus:border-tm-text"
                required
              />
            </div>

            {loginError && (
              <p className="text-red-500 text-xs font-medium">{loginError}</p>
            )}

            <button
              type="submit"
              disabled={loginLoading}
              className="w-full h-9 bg-tm-accent hover:bg-tm-accent/90 transition-colors text-white text-[13px] font-medium rounded-[8px] flex items-center justify-center disabled:opacity-50"
            >
              {loginLoading ? "Authorizing..." : "Authorize"}
            </button>
          </form>
        </div>
      </div>
    );
  }

  // Dashboard Layout Metric data
  const metrics: MetricCardData[] = runData
    ? [
        { label: "Scored", value: runData.total_scored.toLocaleString(), sub: "candidates" },
        { label: "Shortlisted", value: "100", sub: "top candidates" },
        { label: "Honeypots", value: "0%", sub: "in top 100" },
        { label: "Run time", value: `${runData.runtime_seconds}s`, sub: "wall clock" },
      ]
    : [
        { label: "Scored", value: "0", sub: "candidates" },
        { label: "Shortlisted", value: "0", sub: "top candidates" },
        { label: "Honeypots", value: "0%", sub: "in top 100" },
        { label: "Run time", value: "0s", sub: "wall clock" },
      ];

  const hasRuns = runData !== null || activeJobId !== null;

  return (
    <div className="flex flex-col flex-1 h-screen overflow-hidden bg-white select-none">
      {/* Topbar */}
      <header className="h-12 border-b border-tm-border px-6 flex items-center justify-between shrink-0">
        <span className="text-sm font-medium text-tm-text">Candidate Rankings</span>
        <button
          onClick={() => setIsModalOpen(true)}
          className="h-8 px-3 bg-tm-accent text-white hover:bg-tm-accent/90 transition-colors text-[12px] font-medium rounded-[8px] flex items-center gap-1.5"
        >
          <i className="ti ti-plus text-xs" />
          <span>New run</span>
        </button>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
        {loadingLatest ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="animate-spin h-5 w-5 text-tm-accent border-2 border-tm-accent border-t-transparent rounded-full" />
          </div>
        ) : !hasRuns ? (
          /* Empty State */
          <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border border-dashed border-tm-border rounded-[12px] max-w-xl mx-auto my-12 bg-tm-surface/30">
            <i className="ti ti-files text-[32px] text-tm-muted mb-4" />
            <h3 className="text-sm font-medium text-tm-text mb-1">No runs yet</h3>
            <p className="text-[12px] text-tm-muted mb-5 max-w-sm">
              Upload a compressed candidate archive to run the ranking and evaluation pipeline.
            </p>
            <button
              onClick={() => setIsModalOpen(true)}
              className="h-8 px-4 bg-tm-accent text-white hover:bg-tm-accent/90 transition-colors text-[12px] font-medium rounded-[8px]"
            >
              Upload candidate file
            </button>
          </div>
        ) : (
          /* Recruiter Workspace Grid */
          <div className="grid grid-cols-12 gap-6 items-start">
            {/* Main Area */}
            <div className="col-span-8 flex flex-col gap-5">
              <MetricsRow metrics={metrics} />
              
              {runData && (
                <div className="flex flex-col gap-2">
                  <div className="flex justify-between items-center text-[11px] text-tm-muted px-1">
                    <span>Rankings based on Job {runData.job_id}</span>
                    <span>Executed on {new Date(runData.run_at).toLocaleString()}</span>
                  </div>
                  {jdActive && (
                    <div 
                      style={{ backgroundColor: "#FFFBEB", border: "0.5px solid #FDE68A" }} 
                      className="text-[12px] py-2 px-4 rounded-[8px] text-amber-800 font-medium"
                    >
                      Ranked by heuristic score × JD relevance · {jdTokenCount} keywords matched
                    </div>
                  )}
                  <Leaderboard candidates={runData.candidates} jdActive={jdActive} />
                </div>
              )}
            </div>

            {/* Sidebar Controls */}
            <div className="col-span-4 flex flex-col gap-5">
              {/* Progress Indicator (only shows during active run) */}
              {(activeJobId || activeTaskId) && !runData && (
                <PipelineProgress
                  jobId={activeJobId}
                  taskId={activeTaskId}
                  onComplete={handlePipelineComplete}
                />
              )}

              {runData && (
                <JDPanel
                  jobId={runData.job_id}
                  onRerank={handleRerankSuccess}
                />
              )}
            </div>
          </div>
        )}
      </div>

      {/* Upload Modal Overlay */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/10 z-40 flex items-center justify-center p-4">
          <div className="absolute inset-0" onClick={() => setIsModalOpen(false)} />
          <div className="w-full max-w-md border border-tm-border rounded-[12px] p-6 bg-white z-50 flex flex-col gap-4 relative">
            <div className="flex justify-between items-center">
              <h3 className="text-[14px] font-medium text-tm-text">Upload Candidate Pool</h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="text-tm-muted hover:text-tm-text transition-colors"
              >
                <i className="ti ti-x text-base" />
              </button>
            </div>
            <UploadPanel onUploadSuccess={handleUploadSuccess} />
          </div>
        </div>
      )}
    </div>
  );
}
