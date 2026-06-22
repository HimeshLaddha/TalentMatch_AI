"use client";

import React, { useState } from "react";
import { Candidate } from "./Leaderboard";

interface JDPanelProps {
  jobId: string | null;
  onRerank: (
    candidates: Candidate[],
    jdActive: boolean,
    tokenCount: number
  ) => void;
}

export default function JDPanel({ jobId, onRerank }: JDPanelProps) {
  const [jdText, setJdText] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [activeJd, setActiveJd] = useState<string>("");
  const [tokenCount, setTokenCount] = useState<number>(0);

  const jdActive = !!activeJd;

  const handleApply = async () => {
    if (!jobId || !jdText.trim()) return;
    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await fetch("http://localhost:8000/api/v1/pipeline/rerank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          jd_text: jdText.trim(),
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to apply Job Description.");
      }

      const data = await res.json();
      setActiveJd(jdText.trim());
      setTokenCount(data.jd_token_count);
      onRerank(data.candidates, data.jd_active, data.jd_token_count);
    } catch (err) {
      const error = err as Error;
      console.error("Applying JD failed", error);
      setErrorMsg(error.message || "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  const handleClear = async () => {
    if (!jobId) return;
    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await fetch("http://localhost:8000/api/v1/pipeline/rerank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          jd_text: "",
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to clear Job Description.");
      }

      const data = await res.json();
      setJdText("");
      setActiveJd("");
      setTokenCount(0);
      onRerank(data.candidates, false, 0);
    } catch (err) {
      const error = err as Error;
      console.error("Clearing JD failed", error);
      setErrorMsg(error.message || "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div 
      style={{ borderWidth: "0.5px" }} 
      className="border-tm-border rounded-[12px] p-4 bg-white select-none flex flex-col gap-3"
    >
      {/* Label Row */}
      <div className="flex justify-between items-center">
        <span className="text-[13px] font-medium text-tm-text">Job Description</span>
        {jdActive ? (
          <span className="bg-emerald-50 text-emerald-700 px-2.5 py-0.5 rounded-[12px] text-[11px] font-medium border border-emerald-200/50">
            JD Active · {tokenCount} terms
          </span>
        ) : (
          <span className="text-[11px] text-tm-muted">Optional</span>
        )}
      </div>

      {/* Textarea */}
      <textarea
        value={jdText}
        onChange={(e) => setJdText(e.target.value)}
        placeholder="Paste the job description here to boost candidates whose skills and titles match the role..."
        rows={5}
        style={{ borderWidth: "0.5px" }}
        className="w-full text-[13px] leading-[1.6] border-tm-border rounded-[8px] px-3 py-2.5 resize-y focus:outline-none focus:border-tm-text min-h-[100px] md:min-h-[120px]"
        disabled={loading || !jobId}
      />

      {errorMsg && <p className="text-[11px] text-red-500 font-medium">{errorMsg}</p>}

      {/* Button Row */}
      <div className="flex flex-col-reverse md:flex-row justify-between items-stretch md:items-center gap-2 mt-1">
        <div>
          {jdActive && (
            <button
              onClick={handleClear}
              disabled={loading || !jobId}
              className="text-[12px] text-tm-muted hover:text-tm-text transition-colors disabled:opacity-50"
            >
              × Clear JD
            </button>
          )}
        </div>

        <button
          onClick={handleApply}
          disabled={loading || !jobId || !jdText.trim()}
          className="bg-tm-text text-white font-medium hover:bg-tm-text/90 transition-colors text-[12px] py-1.5 px-3.5 rounded-[8px] flex items-center justify-center gap-1.5 disabled:opacity-50 w-full md:w-auto"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Applying…</span>
            </>
          ) : (
            <span>Apply JD</span>
          )}
        </button>
      </div>
    </div>
  );
}
