import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useMe, useSendMagicLink } from "@/lib/api/hooks";

export function SignInRoute() {
  const me = useMe();
  const navigate = useNavigate();
  const sendLink = useSendMagicLink();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (me.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-xs text-[var(--text-tertiary)]">Loading…</p>
      </div>
    );
  }

  // Already signed in — skip the form.
  if (me.data) {
    return <Navigate to="/dashboard" replace />;
  }

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    const normalized = email.trim().toLowerCase();
    if (!normalized || !normalized.includes("@")) {
      setError("Enter a valid email address.");
      return;
    }
    try {
      await sendLink.mutateAsync({ email: normalized });
      navigate(`/magic-link-sent?email=${encodeURIComponent(normalized)}`);
    } catch {
      setError("Something went wrong. Please try again.");
    }
  };

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
        <Card className="p-8">
          <h1
            className="mb-2 text-center text-[28px] leading-tight"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Welcome back
          </h1>
          <p className="mb-6 text-center text-sm text-[var(--text-secondary)]">
            We&apos;ll email you a link to get in. No password required.
          </p>
          <form onSubmit={onSubmit} noValidate className="space-y-4">
            <div>
              <Label htmlFor="email">Email address</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com"
              />
            </div>
            {error ? (
              <p className="text-xs text-[var(--red)]">{error}</p>
            ) : null}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              loading={sendLink.isPending}
            >
              Send magic link
            </Button>
          </form>
        </Card>
      </div>
    </div>
  );
}
