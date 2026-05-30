import os
import shutil
import subprocess
import sys

def main():
    print("Starting TalentMatch AI Monorepo Refactoring...")
    
    # 1. Create directories
    print("Creating directories...")
    os.makedirs("backend", exist_ok=True)
    os.makedirs("frontend", exist_ok=True)
    
    # 2. Relocate backend assets
    backend_assets = [
        "app",
        "tests",
        "requirements.txt",
        ".env.example",
        ".env",
        "run_pipeline_check.py",
        "scaffold_workspace.py"
    ]
    
    for asset in backend_assets:
        if os.path.exists(asset):
            dest = os.path.join("backend", asset)
            if os.path.isdir(asset):
                if os.path.exists(dest):
                    print(f"Destination {dest} already exists. Removing it first...")
                    shutil.rmtree(dest)
                shutil.move(asset, dest)
                print(f"Moved directory {asset} -> {dest}")
            else:
                if os.path.exists(dest):
                    print(f"Destination {dest} already exists. Removing it first...")
                    os.remove(dest)
                shutil.move(asset, dest)
                print(f"Moved file {asset} -> {dest}")
        else:
            print(f"Asset '{asset}' not found, skipping.")
            
    # 3. Update app/core/config.py to load relative path envs
    config_path = "backend/app/core/config.py"
    if os.path.exists(config_path):
        print(f"Updating configuration loading in {config_path}...")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Replace the env_file configuration
        old_pattern = 'env_file=".env"'
        new_pattern = 'env_file=[".env", "backend/.env", "../.env"]'
        if old_pattern in content:
            content = content.replace(old_pattern, new_pattern)
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)
            print("Successfully updated config env file paths.")
        else:
            print("Config env file pattern not found (might be already modified).")
    else:
        print(f"WARNING: config.py not found at {config_path}")

    # 4. Create backend/tests/conftest.py to set PYTHONPATH
    conftest_path = "backend/tests/conftest.py"
    print(f"Writing {conftest_path}...")
    with open(conftest_path, "w", encoding="utf-8") as f:
        f.write('''import os
import sys

# Add backend directory to sys.path so app can be imported properly in tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
''')
    print("conftest.py generated.")

    # 5. Scaffold Next.js in frontend/
    print("Scaffolding Next.js App in frontend/...")
    # Clean the frontend directory if any files exist to ensure create-next-app is happy
    for item in os.listdir("frontend"):
        item_path = os.path.join("frontend", item)
        if os.path.isdir(item_path):
            shutil.rmtree(item_path)
        else:
            os.remove(item_path)
            
    try:
        # Run create-next-app non-interactively using npm/npx
        print("Running npx create-next-app...")
        cmd = [
            "npx", "-y", "create-next-app@15.0.0", "./",
            "--typescript",
            "--tailwind",
            "--eslint",
            "--app",
            "--src-dir",
            "--import-alias", "@/*",
            "--use-npm",
            "--disable-git",
            "--yes"
        ]
        res = subprocess.run(cmd, cwd="frontend", shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            print("Error running create-next-app:")
            print(res.stderr)
            sys.exit(res.returncode)
        else:
            print("Next.js app scaffolded successfully.")
    except Exception as e:
        print(f"Failed to run create-next-app: {e}")
        sys.exit(1)

    # 6. Establish Types (frontend/src/types/index.ts)
    types_dir = "frontend/src/types"
    os.makedirs(types_dir, exist_ok=True)
    types_path = os.path.join(types_dir, "index.ts")
    print(f"Writing data contracts to {types_path}...")
    
    types_content = """export interface JobDescription {
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
  strongly_aligned?: string;
  competency_gaps: string;
  tailored_interview_prompts: string[];
}

export interface MatchResponse {
  matches: CandidateMatch[];
  total_scored: number;
}
"""
    with open(types_path, "w", encoding="utf-8") as f:
        f.write(types_content)
    print("Data contracts written.")

    # 7. Build API Handlers (frontend/src/lib/api.ts)
    lib_dir = "frontend/src/lib"
    os.makedirs(lib_dir, exist_ok=True)
    api_path = os.path.join(lib_dir, "api.ts")
    print(f"Writing API Handlers to {api_path}...")
    
    api_content = """import { CandidateProfile, JobDescription, MatchResponse } from '../types';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export async function ingestCandidateProfile(profile: CandidateProfile): Promise<any> {
  const response = await fetch(`${API_BASE_URL}/profiles/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(profile),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! Status: ${response.status}`);
  }

  return response.json();
}

export async function matchJobDescription(jd: JobDescription): Promise<MatchResponse> {
  const response = await fetch(`${API_BASE_URL}/match/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(jd),
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || `HTTP error! Status: ${response.status}`);
  }

  return response.json();
}
"""
    with open(api_path, "w", encoding="utf-8") as f:
        f.write(api_content)
    print("API Handlers written.")
    print("Refactoring complete. Workspace is structured as a decoupled monorepo.")

if __name__ == "__main__":
    main()
