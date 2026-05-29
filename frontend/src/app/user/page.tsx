"use client";

import React, { useState } from "react";
import { ingestCandidateProfile } from "@/lib/api";
import { CandidateProfile, CareerMilestone } from "@/types";

export default function CandidatePortal() {
  // Candidate profile fields state
  const [candidateId, setCandidateId] = useState("");
  const [name, setName] = useState("");
  const [educationTier, setEducationTier] = useState("Tier_1");
  const [skillsText, setSkillsText] = useState("");
  const [domainsText, setDomainsText] = useState("");
  const [summary, setSummary] = useState("");

  // Platform Signals state
  const [githubScore, setGithubScore] = useState(50);
  const [assessmentPassRate, setAssessmentPassRate] = useState(0.75);
  const [profileCompletion, setProfileCompletion] = useState(85);

  // Career milestones list builder
  const [milestones, setMilestones] = useState<CareerMilestone[]>([]);
  // Individual milestone form state
  const [mTitle, setMTitle] = useState("");
  const [mCompany, setMCompany] = useState("");
  const [mDuration, setMDuration] = useState(12);
  const [mDescription, setMDescription] = useState("");

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  
  // Local session history of ingested profiles
  const [sessionIngested, setSessionIngested] = useState<CandidateProfile[]>([]);

  // Helpers
  const handleGenerateId = () => {
    // Generate a stable-looking candidate identifier
    const rand = Math.floor(1000 + Math.random() * 9000);
    setCandidateId(`CAN-${rand}`);
  };

  const handleAddMilestone = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!mTitle.trim() || !mCompany.trim() || !mDescription.trim()) {
      alert("Please fill in all milestone fields (Title, Company, and Description).");
      return;
    }

    const newMilestone: CareerMilestone = {
      title: mTitle.trim(),
      company: mCompany.trim(),
      duration_months: Number(mDuration),
      role_description: mDescription.trim(),
    };

    setMilestones([...milestones, newMilestone]);
    
    // Clear milestone input fields
    setMTitle("");
    setMCompany("");
    setMDuration(12);
    setMDescription("");
  };

  const handleRemoveMilestone = (index: number) => {
    setMilestones(milestones.filter((_, i) => i !== index));
  };

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccessMessage(null);

    // Validate fields
    if (!candidateId.trim()) {
      setError("Candidate ID is required. Use the generate button or enter a unique code.");
      return;
    }
    if (!name.trim()) {
      setError("Candidate Name is required.");
      return;
    }
    if (!summary.trim()) {
      setError("Career Summary description is required.");
      return;
    }

    const techSkills = skillsText
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    const domainExp = domainsText
      .split(",")
      .map((d) => d.trim())
      .filter((d) => d.length > 0);

    if (techSkills.length === 0) {
      setError("Please provide at least one technical skill.");
      return;
    }

    const profilePayload: CandidateProfile = {
      id: candidateId.trim(),
      name: name.trim(),
      anonymized_tier_education: educationTier,
      domain_experience: domainExp,
      technical_skills: techSkills,
      career_summary: summary.trim(),
      career_history: milestones,
      platform_signals: {
        github_contributions_score: githubScore,
        assessment_pass_rate: assessmentPassRate,
        profile_completion_pct: profileCompletion,
      },
    };

    setIsLoading(true);

    try {
      await ingestCandidateProfile(profilePayload);
      setSuccessMessage(`Candidate profile "${name}" successfully indexed into Vector Store (Qdrant).`);
      setSessionIngested([profilePayload, ...sessionIngested]);

      // Reset main form
      setCandidateId("");
      setName("");
      setSkillsText("");
      setDomainsText("");
      setSummary("");
      setMilestones([]);
      setGithubScore(50);
      setAssessmentPassRate(0.75);
      setProfileCompletion(85);
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Profile ingestion failed. Please verify API server and Qdrant backend status.";
      setError(errMsg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 animate-fade-in">
      {/* Header */}
      <div className="border-b border-slate-800 pb-6">
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
          Candidate Ingestion Portal
        </h1>
        <p className="text-slate-400 text-sm mt-1">
          Index new candidate resumes, project work milestones, and programmatic scoring signals directly into the dual-space vector indexes.
        </p>
      </div>

      {/* Main Grid: Form on Left, Milestones & session log on Right */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        {/* Left Side: General Profile Form & Sliders */}
        <form onSubmit={handleIngest} className="lg:col-span-7 space-y-6">
          
          {/* Form State Alerts */}
          {error && (
            <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-4 flex items-start gap-3 text-rose-300 text-sm">
              <svg className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div><span className="font-bold">Error:</span> {error}</div>
            </div>
          )}

          {successMessage && (
            <div className="bg-emerald-950/20 border border-emerald-500/30 rounded-xl p-4 flex items-start gap-3 text-emerald-300 text-sm">
              <svg className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div><span className="font-bold">Success:</span> {successMessage}</div>
            </div>
          )}

          {/* Profile Core Data Card */}
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-4">
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2 mb-2">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
              Candidate Profile Setup
            </h2>

            <div className="grid grid-cols-1 gap-4">
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                  Candidate ID
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={candidateId}
                    onChange={(e) => setCandidateId(e.target.value)}
                    placeholder="e.g. CAN-0245"
                    className="flex-1 bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors font-mono"
                    required
                  />
                  <button
                    type="button"
                    onClick={handleGenerateId}
                    className="bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-xl px-3 text-xs font-semibold text-slate-300 transition-colors shrink-0"
                  >
                    Auto Gen
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                  Candidate Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. John Doe"
                  className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                Education Ranking Tier
              </label>
              <select
                value={educationTier}
                onChange={(e) => setEducationTier(e.target.value)}
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
              >
                <option value="Tier_1">Tier 1 - Ivy League / Top National Technical Institutions</option>
                <option value="Tier_2">Tier 2 - Ranked Regional / Highly Competitive Institutions</option>
                <option value="Tier_3">Tier 3 - Standard / General Accredited Education</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                Technical Skills (Comma Separated)
              </label>
              <input
                type="text"
                value={skillsText}
                onChange={(e) => setSkillsText(e.target.value)}
                placeholder="React, Next.js, Node.js, Python, TypeScript, Docker"
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
                required
              />
              {skillsText && (
                <div className="flex flex-wrap gap-1.5 mt-2 bg-slate-900/20 p-2 border border-slate-800/40 rounded-lg">
                  {skillsText.split(",").map((s, i) => {
                    const skill = s.trim();
                    if (!skill) return null;
                    return (
                      <span key={i} className="text-xs bg-indigo-500/10 text-indigo-300 px-2 py-0.5 border border-indigo-500/20 rounded-md">
                        {skill}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                Domain Verticals (Comma Separated)
              </label>
              <input
                type="text"
                value={domainsText}
                onChange={(e) => setDomainsText(e.target.value)}
                placeholder="FinTech, SaaS, Healthcare, E-Commerce"
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors"
              />
              {domainsText && (
                <div className="flex flex-wrap gap-1.5 mt-2 bg-slate-900/20 p-2 border border-slate-800/40 rounded-lg">
                  {domainsText.split(",").map((d, i) => {
                    const dom = d.trim();
                    if (!dom) return null;
                    return (
                      <span key={i} className="text-xs bg-sky-500/10 text-sky-300 px-2 py-0.5 border border-sky-500/20 rounded-md">
                        {dom}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1.5">
                Career Summary
              </label>
              <textarea
                rows={4}
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                placeholder="Summary profile narrative outlining focus areas, technologies, and career trajectory..."
                className="w-full bg-slate-900/60 border border-slate-700/80 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500 transition-colors resize-none leading-relaxed"
                required
              />
            </div>
          </div>

          {/* Platform Signals Numerical Metrics Card */}
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-6">
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Platform Scoring & Signals
            </h2>

            {/* Slider 1: GitHub activity index */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  GitHub Contributions Index
                </span>
                <span className="text-sm font-mono font-bold text-indigo-400">{githubScore} / 100</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={githubScore}
                onChange={(e) => setGithubScore(Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 focus:outline-none"
              />
              <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                <span>0 (Inactive)</span>
                <span>50 (Moderate)</span>
                <span>100 (Hyperactive)</span>
              </div>
            </div>

            {/* Slider 2: Assessment Pass rate */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Programmatic Evaluation Pass Rate
                </span>
                <span className="text-sm font-mono font-bold text-indigo-400">
                  {Math.round(assessmentPassRate * 100)}%
                </span>
              </div>
              <input
                type="range"
                min="0.0"
                max="1.0"
                step="0.01"
                value={assessmentPassRate}
                onChange={(e) => setAssessmentPassRate(Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 focus:outline-none"
              />
              <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                <span>0.0 (No passes)</span>
                <span>0.5 (Average)</span>
                <span>1.0 (Flawless)</span>
              </div>
            </div>

            {/* Slider 3: Profile Completion pct */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Profile Completeness Pct
                </span>
                <span className="text-sm font-mono font-bold text-indigo-400">{profileCompletion}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={profileCompletion}
                onChange={(e) => setProfileCompletion(Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 focus:outline-none"
              />
              <div className="flex justify-between text-[10px] text-slate-500 font-mono">
                <span>0%</span>
                <span>50%</span>
                <span>100% (Fully populated)</span>
              </div>
            </div>
          </div>

          {/* Submit Action Block */}
          <button
            type="submit"
            disabled={isLoading}
            className={`w-full flex items-center justify-center gap-2 rounded-xl py-3.5 px-4 font-semibold text-sm transition-all duration-300 shadow-lg ${
              isLoading
                ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700/50"
                : "bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-600/25 hover:shadow-indigo-500/35 border border-indigo-500/30 hover:scale-[1.01]"
            }`}
          >
            {isLoading ? (
              <>
                <svg className="animate-spin h-5 w-5 text-indigo-400" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                Upserting Vector Indexes...
              </>
            ) : (
              <>
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                Submit Candidate Profile
              </>
            )}
          </button>
        </form>

        {/* Right Side: Career Milestone Builder & Session Index Log */}
        <div className="lg:col-span-5 space-y-6">
          
          {/* Milestone Builder Section */}
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md space-y-4">
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
              Career Milestone Builder
            </h2>

            {/* Sub-form */}
            <div className="space-y-4 p-4 border border-slate-800 bg-slate-900/20 rounded-xl">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                    Role Title
                  </label>
                  <input
                    type="text"
                    value={mTitle}
                    onChange={(e) => setMTitle(e.target.value)}
                    placeholder="e.g. Senior Frontend Dev"
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                    Company Name
                  </label>
                  <input
                    type="text"
                    value={mCompany}
                    onChange={(e) => setMCompany(e.target.value)}
                    placeholder="e.g. Stripe"
                    className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Duration (Months)
                </label>
                <input
                  type="number"
                  min="1"
                  value={mDuration}
                  onChange={(e) => setMDuration(Number(e.target.value))}
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
                  Responsibilities & Accomplishments
                </label>
                <textarea
                  rows={3}
                  value={mDescription}
                  onChange={(e) => setMDescription(e.target.value)}
                  placeholder="Developed internal tooling in Next.js. Refactored state handling..."
                  className="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none"
                />
              </div>

              <button
                type="button"
                onClick={handleAddMilestone}
                className="w-full bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-400 border border-indigo-500/20 rounded-lg py-1.5 text-xs font-semibold transition-colors"
              >
                + Add Milestone to History
              </button>
            </div>

            {/* List of Milestones */}
            <div className="space-y-2 mt-4">
              <span className="block text-xs font-semibold uppercase tracking-wider text-slate-400">
                Milestones ({milestones.length})
              </span>
              
              {milestones.length === 0 ? (
                <div className="text-center p-4 border border-dashed border-slate-800/80 rounded-xl text-slate-600 text-xs italic">
                  No professional history milestones added. Add milestones using the builder above.
                </div>
              ) : (
                <div className="space-y-3 max-h-60 overflow-y-auto scrollbar-thin pr-1">
                  {milestones.map((milestone, idx) => (
                    <div key={idx} className="bg-slate-900/60 border border-slate-850 rounded-xl p-3 flex gap-3 items-start justify-between group relative">
                      <div className="space-y-1">
                        <div className="font-semibold text-xs text-slate-200">
                          {milestone.title}
                        </div>
                        <div className="text-[11px] text-slate-400 font-medium">
                          {milestone.company} &bull; <span className="font-mono text-indigo-400">{milestone.duration_months} mo</span>
                        </div>
                        <div className="text-[11px] text-slate-500 leading-relaxed max-w-sm line-clamp-2">
                          {milestone.role_description}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveMilestone(idx)}
                        className="text-rose-500 hover:text-rose-400 hover:bg-rose-950/20 p-1.5 rounded-lg border border-transparent hover:border-rose-900/30 transition-colors shrink-0"
                        title="Remove milestone"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Session Log Card */}
          <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 shadow-xl backdrop-blur-md">
            <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2 mb-4">
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              Session Ingestion History
            </h2>

            {sessionIngested.length === 0 ? (
              <div className="border border-dashed border-slate-800 rounded-xl p-6 text-center text-slate-600 text-xs italic bg-slate-900/10">
                No candidate profiles index queries submitted in this session.
              </div>
            ) : (
              <div className="space-y-2.5 max-h-56 overflow-y-auto scrollbar-thin">
                {sessionIngested.map((profile, i) => (
                  <div key={i} className="flex items-center justify-between p-3 bg-slate-900/40 border border-slate-800/80 rounded-xl text-xs animate-fade-in">
                    <div>
                      <div className="font-semibold text-slate-200">{profile.name}</div>
                      <div className="text-[10px] text-slate-500 font-mono mt-0.5">{profile.id}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-[10px] font-mono text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full uppercase">
                        Indexed
                      </div>
                      <div className="text-[9px] text-slate-500 mt-1 font-mono">{profile.technical_skills.length} skills</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
