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
    <div className="flex min-h-screen items-center justify-center px-5">
      <Card className="w-full max-w-sm">
        <div className="mb-4 flex items-center gap-2">
          <span className="text-base font-normal tracking-tight" style={{ fontFamily: "'DM Serif Display', serif" }}>Kleiber</span>
        </div>
        <h1 className="mb-1 text-xl font-medium">Sign in</h1>
        <p className="mb-5 text-xs text-[var(--text-secondary)]">
          We&apos;ll email you a link to get in. No password required.
        </p>
        <form onSubmit={onSubmit} noValidate>
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
          {error ? (
            <p className="mt-2 text-xs text-[var(--red)]">{error}</p>
          ) : null}
          <Button
            type="submit"
            className="mt-4 w-full"
            loading={sendLink.isPending}
          >
            Send magic link
          </Button>
        </form>
      </Card>
    </div>
  );
}
