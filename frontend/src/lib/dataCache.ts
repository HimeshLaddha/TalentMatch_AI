// Simple in-memory cache — survives tab switching (React keeps module state)
// but clears on full page refresh (correct behaviour for fresh data).

interface CacheEntry<T> {
  data: T;
  fetchedAt: number;
  ttl: number; // milliseconds
}

const store = new Map<string, CacheEntry<unknown>>();

export function getCached<T>(key: string): T | null {
  const entry = store.get(key) as CacheEntry<T> | undefined;
  if (!entry) return null;
  if (Date.now() - entry.fetchedAt > entry.ttl) {
    store.delete(key);
    return null;
  }
  return entry.data;
}

export function setCached<T>(key: string, data: T, ttlMs = 60_000): void {
  store.set(key, { data, fetchedAt: Date.now(), ttl: ttlMs });
}

export function invalidateCache(key: string): void {
  store.delete(key);
}
