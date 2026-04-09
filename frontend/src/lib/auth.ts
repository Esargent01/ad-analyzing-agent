/**
 * Tiny cookie helper used by the API client to attach the double-submit
 * CSRF token on state-changing requests.
 *
 * The backend sets two cookies on sign-in:
 *   - session_token (HttpOnly — we can't read it, it rides along automatically)
 *   - csrf_token    (readable  — we copy it into the X-CSRF-Token header)
 */

export function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const target = `${name}=`;
  const parts = document.cookie ? document.cookie.split(";") : [];
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed.startsWith(target)) {
      return decodeURIComponent(trimmed.substring(target.length));
    }
  }
  return null;
}

export function getCsrfToken(): string | null {
  return readCookie("csrf_token");
}
