const ACTOR_STORAGE_KEY = "actor";
const DEFAULT_ACTOR = "Administrator";

export function getCurrentActor(): string {
  if (typeof window === "undefined") return DEFAULT_ACTOR;

  try {
    const stored = window.sessionStorage.getItem(ACTOR_STORAGE_KEY);
    return stored?.trim() || DEFAULT_ACTOR;
  } catch {
    return DEFAULT_ACTOR;
  }
}

export function setCurrentActor(actor: string): void {
  if (typeof window === "undefined") return;

  const normalized = actor.trim() || DEFAULT_ACTOR;
  window.sessionStorage.setItem(ACTOR_STORAGE_KEY, normalized);
}
