import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/Button";
import { useLogout, useMe, qk } from "@/lib/api/hooks";

export function Header() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useMe();
  const logout = useLogout();

  const onLogout = async () => {
    try {
      await logout.mutateAsync();
    } finally {
      queryClient.setQueryData(qk.me, null);
      queryClient.invalidateQueries({ queryKey: qk.me });
      navigate("/sign-in", { replace: true });
    }
  };

  return (
    <header className="border-b border-[var(--border)] bg-[var(--bg)]">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-5">
        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-[var(--text)] no-underline hover:no-underline"
        >
          <span className="text-base font-normal tracking-tight" style={{ fontFamily: "'DM Serif Display', serif" }}>Kleiber</span>
        </Link>
        <div className="flex items-center gap-3">
          {me.data ? (
            <>
              <span className="text-xs text-[var(--text-secondary)]">
                {me.data.email}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={onLogout}
                loading={logout.isPending}
              >
                Sign out
              </Button>
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}
