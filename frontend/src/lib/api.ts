import { CandidateProfile, JobDescription, MatchResponse, CandidateMatch } from '../types';

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

// ---------------------------------------------------------------------------
// Shared response types for the persistence / recovery layer
// ---------------------------------------------------------------------------

/** A lightweight summary of a single candidate stored on disk. */
export interface StoredCandidateSummary {
  candidate_id: string;
  name: string;
  stored_at: string | null;
  profile_path: string | null;
}

/**
 * Full response shape returned by `GET /profiles/directory`.
 * Describes the physical disk storage registry.
 */
export interface CandidatesDirectoryResponse {
  total_stored: number;
  storage_path: string;
  candidates: StoredCandidateSummary[];
}

/** Per-candidate failure record inside a recovery sync response. */
export interface RecoverySyncError {
  candidate_id: string;
  error: string;
}

/**
 * Full response shape returned by `POST /profiles/sync-recovery`.
 * Summarises which profiles were successfully re-indexed into Qdrant.
 */
export interface RecoverySyncResponse {
  /** "ok" | "partial" | "failed" | "no_profiles" */
  status: 'ok' | 'partial' | 'failed' | 'no_profiles';
  total_found: number;
  synced: number;
  failed: number;
  errors: RecoverySyncError[];
}

// ---------------------------------------------------------------------------
// Central fetch helper – consistent error unwrapping across all handlers
// ---------------------------------------------------------------------------

async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers ?? {}),
    },
  });

  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as {
      detail?: string;
    };
    const errorMessage = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;

    if (
      response.status === 401 ||
      response.status === 403 ||
      errorMessage.toLowerCase().includes("token") ||
      errorMessage.toLowerCase().includes("unauthorized")
    ) {
      if (typeof window !== "undefined") {
        localStorage.removeItem("token");
      }
    }

    throw new Error(errorMessage);
  }

  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Existing handlers
// ---------------------------------------------------------------------------

/**
 * Ingests a structured `CandidateProfile` into the TalentMatch AI vector index.
 * Hits `POST /profiles/`.
 */
export async function ingestCandidateProfile(
  profile: CandidateProfile
): Promise<unknown> {
  return apiFetch<unknown>('/profiles/', {
    method: 'POST',
    body: JSON.stringify(profile),
  });
}

/**
 * Sends a job description to the matching pipeline and returns ranked candidates.
 * Hits `POST /match/`.
 */
export async function matchJobDescription(
  jd: JobDescription
): Promise<MatchResponse> {
  return apiFetch<MatchResponse>('/match/', {
    method: 'POST',
    body: JSON.stringify(jd),
  });
}

// ---------------------------------------------------------------------------
// Persistence layer – new handlers
// ---------------------------------------------------------------------------

/**
 * Fetches the disk-storage candidate directory from the backend.
 * Hits `GET /profiles/directory`.
 *
 * Returns a `CandidatesDirectoryResponse` describing every profile that has
 * been persisted in `backend/storage/metadata.json`. Returns `total_stored: 0`
 * on a fresh installation (never throws a 404).
 */
export async function getStoredCandidatesDirectory(): Promise<CandidatesDirectoryResponse> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return apiFetch<CandidatesDirectoryResponse>('/profiles/directory', {
    method: 'GET',
    headers,
  });
}

/**
 * Triggers an in-memory Qdrant vector store recovery synchronisation.
 * Hits `POST /profiles/sync-recovery`.
 *
 * Re-upserts every profile stored in `backend/storage/metadata.json` back into
 * the live Qdrant collection, healing the in-memory index after a backend
 * reboot cycle without requiring manual file re-uploads.
 *
 * Returns a `RecoverySyncResponse` reporting how many profiles were synced.
 */
export async function triggerDatabaseRecoverySync(): Promise<RecoverySyncResponse> {
  return apiFetch<RecoverySyncResponse>('/profiles/sync-recovery', {
    method: 'POST',
  });
}

/**
 * Authenticates the administrative password and returns the signed JWT token.
 * Hits `POST /profiles/login`.
 */
export async function loginAdmin(password: string): Promise<{ token: string }> {
  return apiFetch<{ token: string }>('/profiles/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
}

/**
 * Triggers the administrative candidate evaluation and synchronization pipeline.
 * Hits `POST /profiles/evaluate-and-sync`.
 */
export async function evaluateAndSync(): Promise<{
  status: string;
  total_evaluated: number;
  total_archived_in_mongo: number;
  leaderboard: CandidateMatch[];
}> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return apiFetch<{
    status: string;
    total_evaluated: number;
    total_archived_in_mongo: number;
    leaderboard: CandidateMatch[];
  }>('/profiles/evaluate-and-sync', {
    method: 'POST',
    headers,
  });
}

/**
 * Returns the absolute URL for the memory-streamed CSV export.
 */
export function getExportCsvUrl(): string {
  return `${API_BASE_URL}/profiles/export-csv`;
}


