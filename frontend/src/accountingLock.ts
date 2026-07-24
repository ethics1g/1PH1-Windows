// Simple in-memory unlock flag for the "accounting" section.
// The flag is NEVER persisted — the user is asked for their code every
// time the app is opened / restarted, which matches the elegant
// "unlock screen" UX the user requested.
//
// It is cleared on logout via `resetAccountingLock()`.

let _unlocked = false;

export function isAccountingUnlocked(): boolean {
  return _unlocked;
}

export function markAccountingUnlocked(): void {
  _unlocked = true;
}

export function resetAccountingLock(): void {
  _unlocked = false;
}
