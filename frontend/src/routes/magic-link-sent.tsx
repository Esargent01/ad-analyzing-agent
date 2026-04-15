import { Link, useSearchParams } from "react-router-dom";

import { Card } from "@/components/ui/Card";

export function MagicLinkSentRoute() {
  const [params] = useSearchParams();
  const email = params.get("email");

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg)] px-6">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <span
            className="text-[28px] tracking-tight text-[var(--text)]"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Kleiber
          </span>
        </div>
        <Card className="p-8 text-center">
          <h1
            className="mb-3 text-[28px] leading-tight"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Check your email
          </h1>
          <p className="mb-4 text-sm text-[var(--text-secondary)]">
            {email ? (
              <>
                We just sent a sign-in link to{" "}
                <span className="font-medium text-[var(--text)]">{email}</span>.
              </>
            ) : (
              <>We just sent you a sign-in link.</>
            )}
          </p>
          <p className="mb-6 text-xs text-[var(--text-tertiary)]">
            The link expires in 15 minutes. If you don&apos;t see it, check your
            spam folder.
          </p>
          <Link
            to="/sign-in"
            className="text-[13px] text-[var(--text)] hover:underline"
          >
            Use a different email
          </Link>
        </Card>
      </div>
    </div>
  );
}
