"use client";

import Link from "next/link";

export default function Home() {
  return (
    <div className="p-8 md:p-12 max-w-6xl mx-auto space-y-12 animate-fade-in">
      
      {/* Hero Welcome Banner */}
      <div className="text-center md:text-left space-y-4 max-w-3xl pt-6">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-400 font-mono font-semibold">
          <span className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse"></span>
          Enterprise Talent Sourcing Suite
        </div>
        
        <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent leading-tight">
          TalentMatch AI Sourcing Engine
        </h1>
        
        <p className="text-slate-400 text-lg leading-relaxed">
          Leverage a two-stage vector retrieval architecture and explainable AI (XAI) deep re-ranking pipelines to source, score, and rank top candidate profiles with zero PII bias.
        </p>
      </div>

      {/* Main Pathways Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Pathway 1: Recruiter */}
        <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 hover:border-slate-700/60 transition-all duration-300 shadow-xl backdrop-blur-md flex flex-col justify-between group">
          <div className="space-y-3">
            <div className="w-12 h-12 rounded-xl bg-indigo-600/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 group-hover:scale-105 transition-transform duration-300">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 002 2h2a2 2 0 002-2z" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-slate-100">Recruitment Dashboard</h2>
            <p className="text-slate-400 text-sm leading-relaxed">
              Analyze unstructured job descriptions, extractStack requirements, execute hybrid dual-space vector searches, and view composite candidate rankings with explainable AI fits.
            </p>
          </div>
          <div className="pt-6">
            <Link
              href="/admin"
              className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-all duration-200 shadow-lg shadow-indigo-600/15"
            >
              Access Dashboard
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          </div>
        </div>

        {/* Pathway 2: Candidate Portal */}
        <div className="bg-slate-950/50 border border-slate-800/80 rounded-2xl p-6 hover:border-slate-700/60 transition-all duration-300 shadow-xl backdrop-blur-md flex flex-col justify-between group">
          <div className="space-y-3">
            <div className="w-12 h-12 rounded-xl bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-400 group-hover:scale-105 transition-transform duration-300">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
              </svg>
            </div>
            <h2 className="text-xl font-bold text-slate-100">Candidate Portal</h2>
            <p className="text-slate-400 text-sm leading-relaxed">
              Ingest candidate resume information, build professional milestones, configure GitHub signals and test scores, and index payloads directly into Qdrant vectors.
            </p>
          </div>
          <div className="pt-6">
            <Link
              href="/user"
              className="inline-flex items-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-750 font-semibold text-sm px-4 py-2.5 rounded-xl transition-all duration-200"
            >
              Open Candidate Portal
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          </div>
        </div>
      </div>

      {/* Multi-Vector Retrieval Pipeline Graphic / Info */}
      <div className="bg-slate-950/30 border border-slate-800/80 rounded-2xl p-8 space-y-6">
        <h3 className="text-lg font-bold text-slate-200">
          Engine Pipeline Lifecycle
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-xs leading-relaxed">
          <div className="space-y-2 p-4 bg-slate-900/30 border border-slate-800/40 rounded-xl">
            <div className="font-mono text-indigo-400 font-semibold">STAGE 1: Parsing & Intent</div>
            <p className="text-slate-500">
              The raw Job Description is processed using an LLM to infer seniority levels, target domains, and implicit stacking keywords.
            </p>
          </div>
          <div className="space-y-2 p-4 bg-slate-900/30 border border-slate-800/40 rounded-xl">
            <div className="font-mono text-indigo-400 font-semibold">STAGE 2: Multi-Vector Search</div>
            <p className="text-slate-500">
              Parallel queries are launched across named vector spaces (technical skills and career trajectory) and SPLADE lexical sparse vectors in Qdrant, fused via Reciprocal Rank Fusion (RRF).
            </p>
          </div>
          <div className="space-y-2 p-4 bg-slate-900/30 border border-slate-800/40 rounded-xl">
            <div className="font-mono text-indigo-400 font-semibold">STAGE 3: XAI Reranking</div>
            <p className="text-slate-500">
              PII is stripped, and a multi-dimensional re-ranking matrix scores candidates across fit, trajectory, signals, and domains, generating explainable feedback narratives.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
