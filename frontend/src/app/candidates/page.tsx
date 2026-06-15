"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";

interface Skill {
  name: string;
  last_used_year?: number;
}

interface CareerHistoryItem {
  title: string;
  company: string;
  years: number;
}

interface Candidate {
  candidate_id: string;
  name: string;
  email: string;
  current_title: string;
  years_of_experience: number;
  last_score: number;
  last_rank: number;
  last_seen: string;
  upload_source: string;
  skills: Skill[];
  career_history: CareerHistoryItem[];
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [minYoe, setMinYoe] = useState("");
  const [maxYoe, setMaxYoe] = useState("");
  const [minScore, setMinScore] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Candidate | null>(null);
  const [token, setToken] = useState<string | null>(null);

  // Load Auth Token
  useEffect(() => {
    setToken(localStorage.getItem("token"));
  }, []);

  // Debounce search input by 300ms
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1); // Reset to first page on new search
    }, 300);

    return () => {
      clearTimeout(handler);
    };
  }, [search]);

  // Fetch candidates from database
  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams();
    if (debouncedSearch) params.set("search", debouncedSearch);
    if (minYoe) params.set("min_yoe", minYoe);
    if (maxYoe) params.set("max_yoe", maxYoe);
    if (minScore) params.set("min_score", minScore);
    if (sourceFilter) params.set("source", sourceFilter);
    params.set("page", String(page));
    params.set("page_size", "50");
    params.set("sort_by", "last_score");

    const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

    fetch(`${API_BASE_URL}/candidates?${params}`)
      .then((r) => r.json())
      .then((data) => {
        setCandidates(data.candidates || []);
        setTotal(data.total || 0);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to fetch candidates", err);
        setCandidates([]);
        setTotal(0);
        setLoading(false);
      });
  }, [debouncedSearch, minYoe, maxYoe, minScore, sourceFilter, page]);

  // Reset page on filter changes
  const handleMinYoeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setMinYoe(e.target.value);
    setPage(1);
  };

  const handleMaxYoeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setMaxYoe(e.target.value);
    setPage(1);
  };

  const handleMinScoreChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setMinScore(e.target.value);
    setPage(1);
  };

  const handleSourceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSourceFilter(e.target.value);
    setPage(1);
  };

  // Pure JS relative date formatter
  function formatRelative(dateStr: string): string {
    if (!dateStr) return "—";
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffSec = Math.floor(diffMs / 1000);
      const diffMin = Math.floor(diffSec / 60);
      const diffHr = Math.floor(diffMin / 60);
      const diffDays = Math.floor(diffHr / 24);

      if (diffSec < 60) {
        return "just now";
      } else if (diffMin < 60) {
        return `${diffMin} min ago`;
      } else if (diffMin === 60) {
        return "1 hour ago";
      } else if (diffHr < 24) {
        return `${diffHr} hours ago`;
      } else if (diffDays === 1) {
        return "yesterday";
      } else if (diffDays < 7) {
        return `${diffDays} days ago`;
      } else {
        return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      }
    } catch {
      return dateStr;
    }
  }

  // Get pill styles for source format
  function getSourcePillClass(source: string): string {
    const base = "inline-flex items-center px-2 py-0.5 rounded-[4px] text-[11px] font-medium border ";
    switch (source?.toLowerCase()) {
      case "pdf":
        return base + "bg-blue-50 text-blue-700 border-blue-200/50";
      case "docx":
        return base + "bg-purple-50 text-purple-700 border-purple-200/50";
      case "json":
        return base + "bg-amber-50 text-amber-700 border-amber-200/50";
      case "jsonl.gz":
        return base + "bg-green-50 text-green-700 border-green-200/50";
      default:
        return base + "bg-zinc-50 text-zinc-600 border-zinc-200/50";
    }
  }

  // Check auth
  if (!token) {
    return (
      <div className="p-8 text-center text-tm-muted select-none text-[13px] my-12">
        Please log in to view candidate profiles.
      </div>
    );
  }

  const totalPages = Math.ceil(total / 50) || 1;

  return (
    <div className="flex flex-col flex-1 h-screen overflow-hidden bg-white select-none">
      {/* Topbar */}
      <header className="h-12 border-b border-tm-border px-6 flex items-center justify-between shrink-0 bg-white">
        <div className="flex flex-col">
          <h1 className="text-sm font-medium text-tm-text">Candidates</h1>
          <span className="text-[11px] text-tm-muted mt-0.5">{total} profiles</span>
        </div>
        <div>
          <select
            value={sourceFilter}
            onChange={handleSourceChange}
            className="h-8 px-3 border border-tm-border rounded-[8px] text-[12px] font-medium bg-white focus:outline-none focus:border-tm-text cursor-pointer"
          >
            <option value="">All sources</option>
            <option value="pdf">pdf</option>
            <option value="docx">docx</option>
            <option value="json">json</option>
            <option value="jsonl.gz">jsonl.gz</option>
          </select>
        </div>
      </header>

      {/* Filter Row */}
      <div className="px-6 py-3 border-b border-tm-border flex items-center gap-3 bg-white shrink-0">
        <div className="relative flex-1">
          <i className="ti ti-search absolute left-3 top-1/2 -translate-y-1/2 text-tm-muted text-sm" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name, title, email, or ID..."
            className="w-full h-9 pl-9 pr-3 border border-tm-border rounded-[8px] text-[13px] focus:outline-none focus:border-tm-text"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[12px] text-tm-muted font-medium">YoE:</span>
          <input
            type="number"
            value={minYoe}
            onChange={handleMinYoeChange}
            placeholder="Min"
            className="w-[60px] h-9 px-2 border border-tm-border rounded-[8px] text-[13px] focus:outline-none focus:border-tm-text text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
          <span className="text-tm-muted text-xs">—</span>
          <input
            type="number"
            value={maxYoe}
            onChange={handleMaxYoeChange}
            placeholder="Max"
            className="w-[60px] h-9 px-2 border border-tm-border rounded-[8px] text-[13px] focus:outline-none focus:border-tm-text text-center [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
          />
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[12px] text-tm-muted font-medium">Score:</span>
          <input
            type="number"
            step="0.01"
            value={minScore}
            onChange={handleMinScoreChange}
            placeholder="0.00–1.00"
            className="w-[90px] h-9 px-2 border border-tm-border rounded-[8px] text-[13px] focus:outline-none focus:border-tm-text text-center"
          />
        </div>
      </div>

      {/* Main Table Area */}
      <div className="flex-1 overflow-y-auto px-6 py-4 bg-white">
        {loading ? (
          /* Loading Skeleton Rows */
          <div className="border border-tm-border rounded-[12px] overflow-hidden bg-white divide-y divide-tm-border">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="p-4 flex items-center gap-4 animate-pulse">
                <div className="w-8 h-4 bg-zinc-200 rounded" />
                <div className="w-[180px] flex flex-col gap-1.5">
                  <div className="h-4 bg-zinc-200 rounded w-3/4" />
                  <div className="h-3 bg-zinc-100 rounded w-1/2" />
                </div>
                <div className="w-[180px] h-4 bg-zinc-200 rounded" />
                <div className="w-[150px] h-3 bg-zinc-200 rounded" />
                <div className="w-[60px] h-4 bg-zinc-200 rounded" />
                <div className="w-[80px] h-4 bg-zinc-200 rounded" />
                <div className="w-[100px] h-4 bg-zinc-200 rounded ml-auto" />
              </div>
            ))}
          </div>
        ) : total === 0 ? (
          /* Empty Database State */
          <div className="flex flex-col items-center justify-center text-center p-12 border border-dashed border-tm-border rounded-[12px] max-w-xl mx-auto my-12 bg-tm-surface/30">
            <i className="ti ti-database-off text-[32px] text-tm-muted mb-4" />
            <h3 className="text-sm font-medium text-tm-text mb-1">No candidates found</h3>
            <p className="text-[12px] text-tm-muted mb-5 max-w-sm">
              Upload a resume or candidate file to populate the database.
            </p>
            <Link
              href="/upload"
              className="h-8 px-4 bg-tm-accent text-white hover:bg-tm-accent/90 transition-colors text-[12px] font-medium rounded-[8px] flex items-center justify-center"
            >
              Go to Upload
            </Link>
          </div>
        ) : (
          /* Grid Pseudotable Container */
          <div className="border border-tm-border rounded-[12px] overflow-hidden bg-white flex flex-col">
            {/* Header */}
            <div className="bg-tm-surface text-[11px] uppercase tracking-wider text-tm-muted border-b border-tm-border py-2.5 px-4 flex items-center font-medium">
              <div className="w-[50px] shrink-0">Rank</div>
              <div className="flex-1 min-w-0 pr-4">Candidate</div>
              <div className="flex-1 min-w-0 pr-4">Title</div>
              <div className="w-[100px] shrink-0 pr-4">Score</div>
              <div className="w-[60px] shrink-0 pr-4">YoE</div>
              <div className="w-[80px] shrink-0 pr-4">Source</div>
              <div className="w-[120px] shrink-0 text-right">Last seen</div>
            </div>

            {/* Rows list */}
            <div className="divide-y divide-tm-border text-[13px] text-tm-text">
              {candidates.map((cand) => {
                const isTop3 = cand.last_rank <= 3;
                return (
                  <div
                    key={cand.candidate_id}
                    onClick={() => setSelected(cand)}
                    className="hover:bg-tm-surface/50 transition-colors flex items-center py-3 px-4 text-left w-full cursor-pointer"
                  >
                    {/* Rank cell */}
                    <div
                      className={`w-[50px] shrink-0 font-medium ${
                        isTop3 ? "text-[#B8820A]" : "text-tm-muted"
                      }`}
                    >
                      #{cand.last_rank}
                    </div>

                    {/* Candidate cell */}
                    <div className="flex-1 min-w-0 pr-4 flex flex-col gap-0.5">
                      <span className="font-medium truncate text-tm-text">{cand.candidate_id}</span>
                      <span className="text-[11px] text-tm-muted truncate">
                        {cand.name || "—"}
                      </span>
                    </div>

                    {/* Title cell */}
                    <div className="flex-1 min-w-0 pr-4 text-[12px] text-tm-text truncate">
                      {cand.current_title || "—"}
                    </div>

                    {/* Score cell */}
                    <div className="w-[100px] shrink-0 pr-4 flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-zinc-100 rounded-[2px] overflow-hidden">
                        <div
                          className="h-full bg-tm-accent"
                          style={{
                            width: `${Math.min(1.0, Math.max(0.0, cand.last_score)) * 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-[12px] font-mono text-tm-text shrink-0 w-[28px] text-right">
                        {cand.last_score.toFixed(2)}
                      </span>
                    </div>

                    {/* YoE cell */}
                    <div className="w-[60px] shrink-0 pr-4 text-tm-text text-[12px]">
                      {cand.years_of_experience} yrs
                    </div>

                    {/* Source cell */}
                    <div className="w-[80px] shrink-0 pr-4">
                      <span className={getSourcePillClass(cand.upload_source)}>
                        {cand.upload_source}
                      </span>
                    </div>

                    {/* Last seen cell */}
                    <div className="w-[120px] shrink-0 text-right text-tm-muted text-[12px]">
                      {formatRelative(cand.last_seen)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Pagination Bar */}
      {total > 0 && (
        <div className="h-12 border-t border-tm-border px-6 flex items-center justify-between shrink-0 bg-white">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="h-8 px-3 border border-tm-border rounded-[8px] text-[12px] text-tm-text bg-white hover:bg-tm-surface disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
          >
            ← Previous
          </button>
          <span className="text-[12px] text-tm-muted font-medium">
            Page {page} of {totalPages} · {total} candidates
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="h-8 px-3 border border-tm-border rounded-[8px] text-[12px] text-tm-text bg-white hover:bg-tm-surface disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
          >
            Next →
          </button>
        </div>
      )}

      {/* Selected Drawer Backdrop */}
      {selected && (
        <div
          onClick={() => setSelected(null)}
          className="fixed inset-0 bg-black/15 z-40 transition-opacity duration-300"
        />
      )}

      {/* Drawer */}
      <div
        className={`fixed right-0 top-0 h-full w-[400px] bg-white border-l border-tm-border z-50 flex flex-col p-6 shadow-xl transition-transform duration-300 ease-out transform ${
          selected ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {selected && (
          <div className="flex-1 flex flex-col gap-6 overflow-y-auto pr-1">
            {/* Header */}
            <div className="flex justify-between items-start">
              <div className="flex flex-col gap-0.5">
                <span className="text-[11px] uppercase tracking-wider text-tm-muted font-medium">
                  Candidate Profile
                </span>
                <h3 className="text-[16px] font-medium text-tm-text truncate w-[280px]">
                  {selected.candidate_id}
                </h3>
              </div>
              <button
                onClick={() => setSelected(null)}
                className="text-tm-muted hover:text-tm-text transition-colors p-1"
              >
                <i className="ti ti-x text-lg" />
              </button>
            </div>

            {/* Profile Info Section */}
            <div className="border-t border-tm-border pt-4 flex flex-col gap-2.5">
              <h4 className="text-[12px] uppercase tracking-wider text-tm-muted font-medium">
                Identity Profile
              </h4>
              <div className="grid grid-cols-3 gap-y-2 text-[13px]">
                <span className="text-tm-muted">Name:</span>
                <span className="col-span-2 text-tm-text font-medium">{selected.name || "—"}</span>

                <span className="text-tm-muted">Email:</span>
                <span className="col-span-2 text-tm-text truncate font-mono select-text">{selected.email || "—"}</span>

                <span className="text-tm-muted">Title:</span>
                <span className="col-span-2 text-tm-text truncate">{selected.current_title || "—"}</span>

                <span className="text-tm-muted">Experience:</span>
                <span className="col-span-2 text-tm-text">{selected.years_of_experience} yrs</span>
              </div>
            </div>

            {/* Score & Placement Section */}
            <div className="border-t border-tm-border pt-4 flex flex-col gap-2.5">
              <h4 className="text-[12px] uppercase tracking-wider text-tm-muted font-medium">
                Pipeline Score
              </h4>
              <div className="flex items-baseline gap-2">
                <span className="text-[20px] font-medium text-tm-text leading-none">
                  {selected.last_score.toFixed(4)}
                </span>
                <span className="text-[12px] text-tm-muted">
                  Ranked #{selected.last_rank} overall
                </span>
              </div>
              <div className="flex items-center gap-4 text-[12px] text-tm-muted mt-1">
                <div className="flex items-center gap-1">
                  <i className="ti ti-clock" />
                  <span>{formatRelative(selected.last_seen)}</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className={getSourcePillClass(selected.upload_source)}>
                    {selected.upload_source}
                  </span>
                </div>
              </div>
            </div>

            {/* Skills Section */}
            {selected.skills && selected.skills.length > 0 && (
              <div className="border-t border-tm-border pt-4 flex flex-col gap-2.5">
                <h4 className="text-[12px] uppercase tracking-wider text-tm-muted font-medium">
                  Skills Matrix
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {selected.skills.map((skill, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center bg-tm-surface px-2.5 py-1 border border-tm-border rounded-[20px] text-[12px] text-tm-text font-medium"
                    >
                      {skill.name}
                      {skill.last_used_year && (
                        <span className="text-[10px] text-tm-muted ml-1 font-mono">
                          ({skill.last_used_year})
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Career History Section */}
            {selected.career_history && selected.career_history.length > 0 && (
              <div className="border-t border-tm-border pt-4 flex flex-col gap-2.5">
                <h4 className="text-[12px] uppercase tracking-wider text-tm-muted font-medium">
                  Career History
                </h4>
                <div className="flex flex-col gap-3">
                  {selected.career_history.map((job, i) => (
                    <div key={i} className="flex flex-col gap-0.5 text-[13px] leading-relaxed">
                      <div className="font-medium text-tm-text">
                        {job.title} <span className="text-tm-muted font-normal">at</span>{" "}
                        {job.company}
                      </div>
                      <div className="text-[11px] text-tm-muted font-medium">
                        {job.years.toFixed(1)} yrs duration
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
        <div className="border-t border-tm-border pt-4 mt-auto shrink-0">
          <button
            onClick={() => setSelected(null)}
            className="w-full text-center px-4 py-2 border border-tm-border rounded-[8px] text-[13px] text-tm-text hover:bg-tm-surface transition-colors font-medium"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
