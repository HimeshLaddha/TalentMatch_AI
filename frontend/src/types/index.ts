export interface JobDescription {
  title: string;
  raw_text: string;
  domain?: string;
}

export interface ParsedJobIntent {
  must_have_skills: string[];
  nice_to_have_skills: string[];
  implicit_inferred_competencies: string[];
  minimum_years_experience: number;
  target_domains: string[];
  seniority_tier: string;
}

export interface CareerMilestone {
  title: string;
  company: string;
  duration_months: number;
  role_description: string;
}

export interface PlatformMetrics {
  github_contributions_score: number;
  assessment_pass_rate: number;
  profile_completion_pct: number;
}

export interface CandidateProfile {
  id: string;
  name: string;
  anonymized_tier_education: string;
  domain_experience: string[];
  technical_skills: string[];
  career_summary: string;
  career_history: CareerMilestone[];
  platform_signals: PlatformMetrics;
}

export interface CandidateMatch {
  candidate_id: string;
  name: string;
  rrf_score: number;
  role_fit_score: number;
  trajectory_score: number;
  platform_signals_score: number;
  domain_alignment_score: number;
  final_score: number;
  strongest_alignment: string;
  competency_gaps: string;
  tailored_interview_prompts: string[];
}

export interface MatchResponse {
  matches: CandidateMatch[];
  total_scored: number;
}
