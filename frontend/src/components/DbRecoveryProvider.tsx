"use client";

import { useEffect, useRef } from "react";
import { triggerDatabaseRecoverySync } from "@/lib/api";

/**
 * DbRecoveryProvider
 * ------------------
 * A lightweight client-side provider that fires `POST /profiles/sync-recovery`
 * exactly once per browser tab session, regardless of Next.js HMR hot-reloads
 * in development.
 *
 * Implementation strategy:
 *   - `sessionStorage` is used as the source of truth. It survives HMR module
 *     re-evaluation (which resets module-level `let` variables) but is cleared
 *     when the tab closes — matching the intended "once per session" semantics.
 *   - `useRef` provides an additional in-memory guard against React Strict Mode's
 *     deliberate double-invocation of effects in development.
 *
 * This guarantees the in-memory Qdrant vector store is fully healed from the
 * persisted `backend/storage/metadata.json` registry as soon as any route in
 * the application mounts, preventing stale-index errors on backend reboot
 * cycles regardless of which page the user navigates to first.
 *
 * The call is intentionally fire-and-forget at the layout level – the Admin
 * Dashboard carries its own `useEffect` that additionally calls
 * `getStoredCandidatesDirectory()` to surface the accurate candidate count in
 * the header badge.
 */

const SESSION_KEY = "_tm_recovery_fired";

export default function DbRecoveryProvider() {
  /** Extra in-memory guard for React Strict Mode double-invoke in dev. */
  const hasFiredRef = useRef(false);

  useEffect(() => {
    // Primary guard: sessionStorage survives HMR but not tab close
    if (typeof window !== "undefined" && sessionStorage.getItem(SESSION_KEY)) {
      return;
    }
    // Secondary guard: useRef for within-render-cycle Strict Mode protection
    if (hasFiredRef.current) return;

    hasFiredRef.current = true;

    if (typeof window !== "undefined") {
      sessionStorage.setItem(SESSION_KEY, "1");
    }

    triggerDatabaseRecoverySync().catch((err: unknown) => {
      // Swallow silently at the layout level – the Admin page surfaces a
      // detailed error badge if the same call fails there.
      const msg = err instanceof Error ? err.message : String(err);
      console.warn("[TalentMatch] Layout-level DB recovery sync failed:", msg);
    });
  }, []);

  // Renders nothing – pure side-effect component
  return null;
}
