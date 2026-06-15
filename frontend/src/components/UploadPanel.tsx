"use client";

import React, { useState, useRef } from "react";

interface UploadPanelProps {
  onUploadSuccess: (jobId: string, taskId: string) => void;
}

export default function UploadPanel({ onUploadSuccess }: UploadPanelProps) {
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndSetFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const validateAndSetFile = (file: File) => {
    setErrorMsg(null);
    const allowedExtensions = [".pdf", ".docx", ".json", ".jsonl.gz"];
    const isAllowed = allowedExtensions.some(ext => file.name.endsWith(ext));
    if (!isAllowed) {
      setErrorMsg("Invalid file type. Only PDF, DOCX, JSON or .jsonl.gz files are accepted.");
      setSelectedFile(null);
      return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setErrorMsg("File is too large. Maximum size is 500MB.");
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  const startRanking = async () => {
    if (!selectedFile) return;
    setLoading(true);
    setErrorMsg(null);

    const formData = new FormData();
    formData.append("file", selectedFile);

    const token = localStorage.getItem("token");
    const headers: Record<string, string> = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    try {
      const res = await fetch("http://localhost:8000/api/v1/pipeline/upload", {
        method: "POST",
        headers,
        body: formData,
      });

      if (!res.ok) {
        if (res.status === 401 || res.status === 403) {
          throw new Error("Unauthorized access. Please log in on the Admin page.");
        }
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to trigger the pipeline.");
      }

      const data = await res.json();
      onUploadSuccess(data.job_id, data.task_id);
    } catch (err) {
      const error = err as Error;
      console.error("Upload failed", error);
      setErrorMsg(error.message || "Failed to upload file. Verify backend is running.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full flex flex-col gap-4 select-none">
      <div
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`w-full border-[1px] border-dashed rounded-[12px] p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${
          dragActive
            ? "border-black bg-tm-surface"
            : "border-tm-border bg-white hover:bg-tm-surface/20"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.json,.jsonl.gz"
          multiple
          className="hidden"
          onChange={handleFileChange}
          disabled={loading}
        />

        <i className="ti ti-upload text-[32px] text-tm-muted mb-3" />
        <p className="text-[14px] text-tm-text font-medium">
          {selectedFile ? "Selected: " + selectedFile.name : "Drop resumes or candidate files here"}
        </p>
        <p className="text-[12px] text-tm-muted mt-1">
          {selectedFile ? formatFileSize(selectedFile.size) : "PDF, DOCX, JSON or .jsonl.gz · up to 500MB"}
        </p>
      </div>

      {selectedFile && !loading && (
        <div className="flex items-center gap-2 text-tm-success text-xs font-medium justify-center">
          <i className="ti ti-circle-check text-sm" />
          <span>File ready for processing</span>
        </div>
      )}

      {errorMsg && (
        <p className="text-red-500 text-xs font-medium text-center">{errorMsg}</p>
      )}

      {selectedFile && (
        <button
          onClick={startRanking}
          disabled={loading}
          className="w-full h-9 bg-tm-accent text-white hover:bg-tm-accent/90 transition-colors text-[13px] font-medium rounded-[8px] flex items-center justify-center gap-1.5 disabled:opacity-50"
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Uploading…</span>
            </>
          ) : (
            <span>Start ranking</span>
          )}
        </button>
      )}
    </div>
  );
}
