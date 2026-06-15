"use client";

import React, { useState, useEffect } from "react";
import UploadPanel from "@/components/UploadPanel";
import PipelineProgress from "@/components/PipelineProgress";

export default function UploadPage() {
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(localStorage.getItem("token"));
  }, []);

  const handleUploadSuccess = (jobId: string, taskId: string) => {
    setActiveJobId(jobId);
    setActiveTaskId(taskId);
  };

  if (!token) {
    return (
      <div className="p-8 text-center text-tm-muted select-none text-[13px] my-12">
        Please log in to upload candidate files.
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 h-screen overflow-hidden bg-white select-none">
      <header className="h-12 border-b border-tm-border px-6 flex items-center shrink-0">
        <span className="text-sm font-medium text-tm-text">Ingestion Pipeline</span>
      </header>

      <div className="flex-1 overflow-y-auto p-6 max-w-xl mx-auto w-full flex flex-col gap-6 pt-12">
        <div className="flex flex-col gap-1 text-center">
          <h2 className="text-[15px] font-medium text-tm-text">Upload Candidate Archive</h2>
          <p className="text-[12px] text-tm-muted">
            Process a candidate pool `.jsonl.gz` dataset using the Celery evaluation pipeline.
          </p>
        </div>

        <UploadPanel onUploadSuccess={handleUploadSuccess} />

        {(activeJobId || activeTaskId) && (
          <PipelineProgress
            jobId={activeJobId}
            taskId={activeTaskId}
            onComplete={() => alert("Pipeline run completed! View results on Rankings dashboard.")}
          />
        )}
      </div>
    </div>
  );
}
