"use client";

import React, { useEffect, useState, useRef } from "react";

interface PipelineProgressProps {
  jobId: string | null;
  taskId?: string | null;
  onComplete?: () => void;
}

interface SsePayload {
  state: string;
  progress: number;
  detail: string;
}

export default function PipelineProgress({ jobId, taskId, onComplete }: PipelineProgressProps) {
  const [progress, setProgress] = useState<number>(0);
  const [detail, setDetail] = useState<string>("Initializing...");
  const [statusState, setStatusState] = useState<string>("PENDING");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // If taskId is provided, use it, otherwise fall back to jobId
  const targetId = taskId || jobId;

  // Use a ref to store the latest onComplete callback to avoid triggering useEffect when it changes
  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    if (!targetId) {
      setProgress(0);
      setDetail("No active run");
      setStatusState("PENDING");
      setErrorMsg(null);
      return;
    }

    setProgress(0);
    setDetail("Connecting to pipeline status...");
    setStatusState("STARTED");
    setErrorMsg(null);

    const eventSource = new EventSource(`http://localhost:8000/api/v1/pipeline/status/${targetId}`);

    eventSource.onmessage = (event) => {
      try {
        const data: SsePayload = JSON.parse(event.data);
        setProgress(data.progress);
        setDetail(data.detail);
        setStatusState(data.state);

        if (data.state === "SUCCESS") {
          eventSource.close();
          if (onCompleteRef.current) onCompleteRef.current();
        } else if (data.state === "FAILURE" || data.state === "REVOKED") {
          eventSource.close();
          setErrorMsg(data.detail || "Pipeline run failed");
        }
      } catch (err) {
        console.error("Failed to parse SSE payload", err);
      }
    };

    eventSource.onerror = (err) => {
      console.error("SSE Connection error", err);
      if (eventSource.readyState === EventSource.CLOSED) {
        eventSource.close();
        setStatusState("FAILURE");
        setErrorMsg("Failed to connect to status stream.");
      } else {
        setDetail("Reconnecting to pipeline status...");
      }
    };

    return () => {
      eventSource.close();
    };
  }, [targetId]);

  if (!targetId) {
    return (
      <div className="bg-tm-surface rounded-[12px] p-5 border border-tm-border text-center text-[13px] text-tm-muted select-none">
        No active pipeline run. Upload candidates to begin.
      </div>
    );
  }

  const stages = [
    { name: "Parse", threshold: 20 },
    { name: "Heuristics", threshold: 40 },
    { name: "Vector search", threshold: 60 },
    { name: "RRF fusion", threshold: 80 },
    { name: "XAI top-3", threshold: 100 },
  ];

  const isFailed = statusState === "FAILURE" || errorMsg !== null;
  const isComplete = statusState === "SUCCESS" && progress === 100;

  return (
    <div className="bg-tm-surface rounded-[12px] p-5 border border-tm-border select-none relative flex flex-col gap-4">
      {/* Header Row */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-0.5">
          <span className="text-[13px] font-medium text-tm-text">
            Scoring 100,000 candidates
          </span>
          <span className="text-[11px] text-tm-muted truncate max-w-[400px]">
            {isFailed ? errorMsg : detail}
          </span>
        </div>

        <div>
          {isFailed && (
            <span className="bg-red-50 text-red-600 border border-red-200/40 text-[11px] font-medium px-2 py-0.5 rounded-[4px]">
              Failed
            </span>
          )}
          {isComplete && (
            <span className="bg-emerald-50 text-tm-success border border-emerald-200/40 text-[11px] font-medium px-2 py-0.5 rounded-[4px]">
              Complete
            </span>
          )}
          {!isFailed && !isComplete && (
            <span className="text-[13px] font-medium text-tm-text">
              {progress}%
            </span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-[4px] bg-zinc-200 rounded-[2px] overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ease-out ${
            isFailed ? "bg-red-500" : "bg-tm-accent"
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Stage Pills */}
      <div className="flex flex-wrap gap-2 mt-1">
        {stages.map((stage) => {
          const isDone = progress >= stage.threshold;
          return (
            <div
              key={stage.name}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-[8px] text-[13px] border transition-colors ${
                isDone
                  ? "bg-emerald-50 text-tm-success border-emerald-200/30 font-medium"
                  : "bg-white text-tm-muted border-tm-border"
              }`}
            >
              {isDone ? (
                <i className="ti ti-check text-xs" />
              ) : (
                <div className="w-1.5 h-1.5 rounded-full bg-zinc-300" />
              )}
              <span>{stage.name}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
