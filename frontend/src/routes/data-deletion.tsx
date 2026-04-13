import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/lib/api/client";

interface DeletionStatus {
  confirmation_code: string;
  status: string;
  requested_at: string;
}

export function DataDeletionRoute() {
  const { confirmationCode } = useParams<{ confirmationCode: string }>();
  const [deletion, setDeletion] = useState<DeletionStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!confirmationCode) return;

    api
      .get<DeletionStatus>(
        `/api/data-deletion/${confirmationCode}/status`,
      )
      .then(setDeletion)
      .catch(() => setError("Deletion request not found."))
      .finally(() => setLoading(false));
  }, [confirmationCode]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-xs text-[var(--text-tertiary)]">Loading…</p>
      </div>
    );
  }

  if (error || !deletion) {
    return (
      <div className="mx-auto max-w-md px-5 py-12 text-center">
        <h1 className="mb-2 text-xl font-semibold">Not found</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          {error ?? "This deletion request could not be found."}
        </p>
      </div>
    );
  }

  const requestedDate = new Date(deletion.requested_at);

  return (
    <div className="mx-auto max-w-md px-5 py-12">
      <header className="mb-6">
        <h1 className="mb-1 text-xl font-semibold">Data Deletion Status</h1>
        <p className="text-xs text-[var(--text-tertiary)]">
          Ad Creative Agent
        </p>
      </header>

      <div
        className={`rounded-lg border p-5 ${
          deletion.status === "completed"
            ? "border-l-4 border-l-green-500 border-[var(--border)]"
            : "border-l-4 border-l-amber-500 border-[var(--border)]"
        }`}
      >
        <div className="mb-4">
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
            Status
          </p>
          <p className="font-mono text-sm">
            {deletion.status === "completed"
              ? "\u2705 Deletion completed"
              : "\u23F3 Deletion pending"}
          </p>
        </div>

        <div className="mb-4">
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
            Confirmation code
          </p>
          <p className="font-mono text-sm">{deletion.confirmation_code}</p>
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-wider text-[var(--text-tertiary)]">
            Requested at
          </p>
          <p className="font-mono text-sm">
            {requestedDate.toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}{" "}
            at{" "}
            {requestedDate.toLocaleTimeString("en-US", {
              hour: "2-digit",
              minute: "2-digit",
              timeZoneName: "short",
            })}
          </p>
        </div>
      </div>

      <section className="mt-6">
        <h2 className="mb-2 text-sm font-medium">What was deleted</h2>
        <p className="mb-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          The following data associated with your Meta account was permanently
          removed:
        </p>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-sm text-[var(--text-secondary)]">
          <li>Your encrypted Meta OAuth access token</li>
          <li>Your Meta user ID and connected account information</li>
          <li>Ad account and Page associations</li>
        </ul>
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          Campaign performance data (metrics, creative variants, analysis
          results) is retained separately and is not linked to your Meta
          identity. To request full account deletion, contact us at{" "}
          <a
            href="mailto:adagent@company.com"
            className="text-[var(--accent)] hover:underline"
          >
            adagent@company.com
          </a>
          .
        </p>
      </section>

      <footer className="mt-8 border-t border-[var(--border)] pt-4 text-xs text-[var(--text-tertiary)]">
        <Link to="/privacy" className="hover:underline">
          Privacy Policy
        </Link>
      </footer>
    </div>
  );
}
