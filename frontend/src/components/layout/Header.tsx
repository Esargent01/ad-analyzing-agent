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
    <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--bg)]/90 backdrop-blur-sm">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6 sm:px-10 lg:px-16">
        <Link
          to="/dashboard"
          className="flex items-center gap-2 text-[var(--text)] no-underline hover:no-underline"
        >
          <span
            className="text-[22px] tracking-tight"
            style={{ fontFamily: "'DM Serif Display', serif" }}
          >
            Kleiber
          </span>
        </Link>
        <div className="flex items-center gap-4">
          {me.data ? (
            <>
              <span className="hidden text-[13px] text-[var(--text-secondary)] sm:inline-block">
                {me.data.email}
              </span>
              <Button
                variant="secondary"
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
