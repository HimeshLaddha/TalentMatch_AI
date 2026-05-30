"use client";

import React, { useState, useRef } from "react";
import { CandidateProfile } from "@/types";

export default function CandidatePortal() {
  // Drag and drop states
  const [isDragActive, setIsDragActive] = useState(false);
  
  // UI Loading/Error/Success states
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [lastParsedProfile, setLastParsedProfile] = useState<CandidateProfile | null>(null);

  // Local session history of ingested profiles
  const [sessionIngested, setSessionIngested] = useState<CandidateProfile[]>([]);

  // Refs
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Drag handlers
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setIsDragActive(true);
    } else if (e.type === "dragleave") {
      setIsDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragActive(false);
    setError(null);
    setSuccessMessage(null);
    setLastParsedProfile(null);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      validateAndProcessFile(droppedFile);
    }
  };

  // Input change handler
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setSuccessMessage(null);
    setLastParsedProfile(null);
    
    if (e.target.files && e.target.files[0]) {
      validateAndProcessFile(e.target.files[0]);
    }
  };

  // Check file extension
  const validateAndProcessFile = (selectedFile: File) => {
    const filename = selectedFile.name.toLowerCase();
    
    // Explicit constraint check for legacy .doc
    if (filename.endsWith(".doc") && !filename.endsWith(".docx")) {
      setError("Legacy .doc format is not supported. Please save your file as .docx or .pdf for automatic extraction.");
      return;
    }

    if (!(filename.endsWith(".pdf") || filename.endsWith(".docx"))) {
      setError("Unsupported file format. Please upload a PDF (.pdf) or Word document (.docx).");
      return;
    }

    // Auto-upload immediately for frictionless UX
    uploadFile(selectedFile);
  };

  // Upload file via FormData stream
  const uploadFile = async (targetFile: File) => {
    setIsLoading(true);
    setError(null);
    setSuccessMessage(null);
    setLastParsedProfile(null);

    const formData = new FormData();
    formData.append("file", targetFile);

    try {
      const response = await fetch("http://localhost:8000/api/v1/profiles/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Upload failed with status code ${response.status}`);
      }

      const data = await response.json();
      
      // Successfully ingested
      setSuccessMessage(`Resume "${targetFile.name}" successfully parsed and indexed in vector store.`);
      
      if (data.profile) {
        const profile = data.profile as CandidateProfile;
        setLastParsedProfile(profile);
        setSessionIngested((prev) => [profile, ...prev]);
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Failed to process resume upload. Please verify API server is online.";
      setError(errMsg);
    } finally {
      setIsLoading(false);
    }
  };

  const triggerFileSelect = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-fade-in">
      {/* Header */}
      <div className="border-b border-slate-800 pb-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
            Candidate Ingestion Portal
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Upload raw resume files (.pdf or .docx) to automatically parse credentials and generate dual-space vector indexes.
          </p>
        </div>
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900 border border-slate-800 text-xs text-slate-400 font-mono">
          <span className="h-2.5 w-2.5 rounded-full bg-indigo-500 animate-pulse"></span>
          LLM Parsing Pipeline Ready
        </div>
      </div>

      {/* Main Grid: Upload zone on Left, extracted preview or session history on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Column: Drag and Drop Zone */}
        <div className="lg:col-span-6 space-y-6">
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-4">
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              Resume Upload Zone
            </h2>

            {/* Drag & Drop Card container */}
            <div
              onDragEnter={handleDrag}
              onDragOver={handleDrag}
              onDragLeave={handleDrag}
              onDrop={handleDrop}
              onClick={triggerFileSelect}
              className={`h-72 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center text-center p-6 cursor-pointer transition-all duration-300 ${
                isDragActive
                  ? "border-indigo-500 bg-indigo-500/5 shadow-indigo-500/10 shadow-lg"
                  : "border-slate-800 bg-slate-900/10 hover:bg-slate-900/25 hover:border-slate-700/80"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                accept=".pdf,.docx,.doc"
                onChange={handleFileChange}
              />
              
              <div className="w-14 h-14 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mb-4 text-slate-400 shadow-md group-hover:scale-105 transition-transform duration-300">
                <svg className="w-7 h-7 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>

              <h3 className="font-semibold text-slate-200 text-sm">
                Drag and drop resume here
              </h3>
              <p className="text-slate-500 text-xs mt-1.5 max-w-xs">
                Supports PDF (.pdf) and Microsoft Word (.docx) files. Click to browse files from explorer.
              </p>
            </div>
          </div>

          {/* Feedback alerts container */}
          {error && (
            <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-4 flex items-start gap-3 text-rose-300 text-sm animate-fade-in">
              <svg className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <span className="font-bold">Ingestion Blocked:</span> {error}
              </div>
            </div>
          )}

          {successMessage && (
            <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-xl p-4 flex items-start gap-3 text-emerald-300 text-sm animate-fade-in">
              <svg className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <span className="font-bold">Ingestion Success:</span> {successMessage}
              </div>
            </div>
          )}

          {/* Glowing pulse loading banner */}
          {isLoading && (
            <div className="bg-indigo-950/20 border border-indigo-500/30 rounded-xl p-6 shadow-indigo-500/5 shadow-md flex items-center gap-4 animate-pulse">
              <div className="relative shrink-0 flex h-6 w-6">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-6 w-6 bg-indigo-500 flex items-center justify-center text-[10px] text-white font-bold font-mono">AI</span>
              </div>
              <div className="space-y-1">
                <h4 className="text-sm font-semibold text-indigo-300">Extracting Profile</h4>
                <p className="text-xs text-slate-400">
                  AI is analyzing resume layout and generating vector slots... Please wait.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: AI Extraction Insights Preview */}
        <div className="lg:col-span-6 space-y-6">
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md min-h-[352px] flex flex-col justify-between">
            <div>
              <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2 mb-4 border-b border-slate-800/60 pb-3">
                <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
                AI Extraction Preview
              </h2>

              {!lastParsedProfile ? (
                <div className="h-56 flex flex-col items-center justify-center text-center p-6 border border-dashed border-slate-800 rounded-xl text-slate-600 text-xs italic bg-slate-900/10">
                  Drop a PDF or DOCX file on the left. The AI parsing pipeline will automatically extract credentials and show a preview of the structured metadata here.
                </div>
              ) : (
                <div className="space-y-4 text-xs animate-fade-in">
                  {/* General Profile Row */}
                  <div className="grid grid-cols-2 gap-4 bg-slate-900/40 p-3.5 border border-slate-800/80 rounded-xl">
                    <div>
                      <span className="text-slate-500 block uppercase tracking-wider text-[9px] font-semibold">Candidate ID</span>
                      <span className="font-mono text-slate-200 font-bold">{lastParsedProfile.id}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block uppercase tracking-wider text-[9px] font-semibold">Candidate Name</span>
                      <span className="text-slate-200 font-bold">{lastParsedProfile.name}</span>
                    </div>
                  </div>

                  {/* Education and Verticals */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-slate-500 block uppercase tracking-wider text-[9px] font-semibold mb-1">Education Rating</span>
                      <span className="inline-block bg-slate-900 border border-slate-850 px-2.5 py-1 rounded text-slate-300 font-semibold font-mono">
                        {lastParsedProfile.anonymized_tier_education.replace("_", " ")}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500 block uppercase tracking-wider text-[9px] font-semibold mb-1">Extracted Domain</span>
                      <div className="flex flex-wrap gap-1">
                        {lastParsedProfile.domain_experience.slice(0, 3).map((d, i) => (
                          <span key={i} className="bg-sky-500/10 text-sky-400 border border-sky-500/20 px-2 py-0.5 rounded text-[10px]">
                            {d}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Skills tags */}
                  <div>
                    <span className="text-slate-500 block uppercase tracking-wider text-[9px] font-semibold mb-1.5">Extracted Stack / Skills ({lastParsedProfile.technical_skills.length})</span>
                    <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto pr-1">
                      {lastParsedProfile.technical_skills.map((s, i) => (
                        <span key={i} className="bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 px-2 py-0.5 rounded text-[10px]">
                          {s}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Inferred platform activity signals */}
                  <div className="bg-slate-900/30 p-3 border border-slate-800/80 rounded-xl space-y-2">
                    <span className="text-slate-400 block uppercase tracking-wider text-[9px] font-bold">
                      Inferred Platform Activity Signals
                    </span>
                    <div className="grid grid-cols-3 gap-3 text-center text-[10px]">
                      <div className="bg-slate-900 p-2 border border-slate-850 rounded-lg">
                        <span className="text-slate-500 block text-[9px]">GitHub Contributions</span>
                        <span className="font-mono text-indigo-400 font-extrabold">{lastParsedProfile.platform_signals.github_contributions_score} / 100</span>
                      </div>
                      <div className="bg-slate-900 p-2 border border-slate-850 rounded-lg">
                        <span className="text-slate-500 block text-[9px]">Evaluation Pass</span>
                        <span className="font-mono text-indigo-400 font-extrabold">{Math.round(lastParsedProfile.platform_signals.assessment_pass_rate * 100)}%</span>
                      </div>
                      <div className="bg-slate-900 p-2 border border-slate-850 rounded-lg">
                        <span className="text-slate-500 block text-[9px]">Profile Completeness</span>
                        <span className="font-mono text-indigo-400 font-extrabold">{lastParsedProfile.platform_signals.profile_completion_pct}%</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
            
            {/* Download/Vector ID Indicator */}
            {lastParsedProfile && (
              <div className="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between text-[10px] text-slate-500 font-mono">
                <span>Ingested Vector Record</span>
                <span className="text-slate-400 font-bold select-all">Qdrant point generated</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Session Ingestion Log - full width at the bottom */}
      <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md">
        <div className="flex items-center justify-between mb-4 border-b border-slate-800/60 pb-3">
          <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            Session Ingested Profiles Log
          </h2>
          <span className="text-xs text-slate-500 font-mono">
            {sessionIngested.length} profiles index queries submitted
          </span>
        </div>

        {sessionIngested.length === 0 ? (
          <div className="border border-dashed border-slate-800 rounded-xl p-8 text-center text-slate-600 text-xs italic bg-slate-900/10">
            No candidate profiles uploaded in this browser session. Drop a file above to add candidates.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/10">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-slate-800 font-semibold uppercase tracking-wider text-slate-500 bg-slate-900/30">
                  <th className="py-3 px-4">Candidate ID</th>
                  <th className="py-3 px-4">Name</th>
                  <th className="py-3 px-4">Education Rating</th>
                  <th className="py-3 px-4">Technical Stack</th>
                  <th className="py-3 px-4 text-center">GitHub score</th>
                  <th className="py-3 px-4 text-center">Evaluation Pass</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {sessionIngested.map((profile) => (
                  <tr key={profile.id} className="hover:bg-slate-900/20 transition-colors animate-fade-in">
                    <td className="py-3.5 px-4 font-mono font-bold text-indigo-400">{profile.id}</td>
                    <td className="py-3.5 px-4 text-slate-200 font-semibold">{profile.name}</td>
                    <td className="py-3.5 px-4">
                      <span className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-slate-400 font-mono">
                        {profile.anonymized_tier_education}
                      </span>
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="flex flex-wrap gap-1 max-w-sm">
                        {profile.technical_skills.slice(0, 5).map((skill, i) => (
                          <span key={i} className="bg-indigo-500/5 text-indigo-300/80 px-1.5 py-0.5 rounded text-[10px]">
                            {skill}
                          </span>
                        ))}
                        {profile.technical_skills.length > 5 && (
                          <span className="text-[10px] text-slate-500 pl-1 font-mono">+{profile.technical_skills.length - 5} more</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-center font-mono text-slate-300">
                      {profile.platform_signals.github_contributions_score}
                    </td>
                    <td className="py-3.5 px-4 text-center font-mono text-slate-300">
                      {Math.round(profile.platform_signals.assessment_pass_rate * 100)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
