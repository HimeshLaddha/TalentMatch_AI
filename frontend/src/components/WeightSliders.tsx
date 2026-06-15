"use client";

import React, { useState } from "react";
import { Candidate } from "./Leaderboard";

export interface Weights {
  experience: number;
  skills: number;
  signals: number;
}

interface WeightSlidersProps {
  jobId: string | null;
  onRerank: (newCandidates: Candidate[]) => void;
}

export default function WeightSliders({ jobId, onRerank }: WeightSlidersProps) {
  const [weights, setWeights] = useState<Weights>({
    experience: 40,
    skills: 40,
    signals: 20,
  });
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSliderChange = (key: keyof Weights, value: number) => {
    const oldValue = weights[key];
    const delta = value - oldValue;

    const otherKeys = (Object.keys(weights) as Array<keyof Weights>).filter((k) => k !== key);
    const otherSum = otherKeys.reduce((sum, k) => sum + weights[k], 0);

    const newWeights = { ...weights };
    newWeights[key] = value;

    if (otherSum > 0) {
      // Redistribute delta proportionally
      otherKeys.forEach((k) => {
        const share = weights[k] / otherSum;
        newWeights[k] = Math.max(0, Math.min(100, Math.round(weights[k] - delta * share)));
      });
    } else {
      // If others are 0, split the delta equally
      const share = delta / otherKeys.length;
      otherKeys.forEach((k) => {
        newWeights[k] = Math.max(0, Math.min(100, Math.round(weights[k] - share)));
      });
    }

    // Enforce that sum is exactly 100
    const currentSum = newWeights.experience + newWeights.skills + newWeights.signals;
    const discrepancy = 100 - currentSum;

    if (discrepancy !== 0) {
      for (const k of otherKeys) {
        const adjustedVal = newWeights[k] + discrepancy;
        if (adjustedVal >= 0 && adjustedVal <= 100) {
          newWeights[k] = adjustedVal;
          break;
        }
      }
    }

    setWeights(newWeights);
  };

  const triggerRerank = async () => {
    if (!jobId) return;
    setLoading(true);
    setErrorMsg(null);

    try {
      const res = await fetch("http://localhost:8000/api/v1/pipeline/rerank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          weights: {
            experience: weights.experience,
            skills: weights.skills,
            signals: weights.signals,
          },
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to re-rank candidate pool.");
      }

      const data = await res.json();
      onRerank(data);
    } catch (err) {
      const error = err as Error;
      console.error("Reranking failed", error);
      setErrorMsg(error.message || "An unexpected error occurred during re-ranking.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border border-tm-border rounded-[12px] p-5 bg-white select-none flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h4 className="text-[13px] font-medium text-tm-text">Dimensions Scoring Weights</h4>
        <p className="text-[11px] text-tm-muted">
          Adjust coefficients dynamically (total must sum to 100%)
        </p>
      </div>

      <div className="flex flex-col gap-3">
        {/* Experience Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between text-[11px] font-medium">
            <span className="text-tm-text">Experience</span>
            <span className="text-tm-muted font-mono">{weights.experience}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={weights.experience}
            onChange={(e) => handleSliderChange("experience", parseInt(e.target.value))}
            disabled={loading || !jobId}
            className="w-full h-1 bg-zinc-100 rounded-lg appearance-none cursor-pointer accent-tm-accent"
          />
        </div>

        {/* Skills Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between text-[11px] font-medium">
            <span className="text-tm-text">Technical skills</span>
            <span className="text-tm-muted font-mono">{weights.skills}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={weights.skills}
            onChange={(e) => handleSliderChange("skills", parseInt(e.target.value))}
            disabled={loading || !jobId}
            className="w-full h-1 bg-zinc-100 rounded-lg appearance-none cursor-pointer accent-tm-accent"
          />
        </div>

        {/* Signals Slider */}
        <div className="flex flex-col gap-1">
          <div className="flex justify-between text-[11px] font-medium">
            <span className="text-tm-text">Platform signals</span>
            <span className="text-tm-muted font-mono">{weights.signals}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="100"
            step="1"
            value={weights.signals}
            onChange={(e) => handleSliderChange("signals", parseInt(e.target.value))}
            disabled={loading || !jobId}
            className="w-full h-1 bg-zinc-100 rounded-lg appearance-none cursor-pointer accent-tm-accent"
          />
        </div>
      </div>

      {errorMsg && <p className="text-[11px] text-red-500 font-medium">{errorMsg}</p>}

      <button
        onClick={triggerRerank}
        disabled={loading || !jobId}
        className="w-full h-9 bg-tm-accent text-white hover:bg-tm-accent/90 transition-colors text-[13px] font-medium rounded-[8px] flex items-center justify-center gap-1.5 disabled:opacity-50"
      >
        {loading ? (
          <>
            <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span>Re-ranking...</span>
          </>
        ) : (
          <>
            <i className="ti ti-rotate-2 text-sm" />
            <span>Re-rank pool</span>
          </>
        )}
      </button>
    </div>
  );
}
