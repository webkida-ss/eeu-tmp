"use client";

import { useAuth } from "../hooks/useAuth";

type AuthActionButtonProps = {
  variant?: "primary" | "dark";
};

const buttonClassNames = {
  primary:
    "rounded-full bg-amber-400 px-5 py-2 font-bold text-amber-950 shadow-md transition-colors hover:bg-amber-300",
  dark: "rounded-full bg-amber-950 px-10 py-4 font-bold text-amber-50 transition-colors hover:bg-amber-800",
};

const menuButtonClassNames = {
  primary:
    "rounded-full border border-amber-200 bg-white px-4 py-2 text-sm font-bold text-amber-800 shadow-sm transition-colors hover:bg-amber-50",
  dark: "rounded-full border border-amber-800 bg-amber-950 px-5 py-3 text-sm font-bold text-amber-50 transition-colors hover:bg-amber-900",
};

export function AuthActionButton({ variant = "primary" }: AuthActionButtonProps) {
  const { user, status, login, logout } = useAuth();
  const isLoading = status === "loading";

  if (user) {
    return (
      <details className="group relative">
        <summary
          className={`${menuButtonClassNames[variant]} flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden`}
        >
          <span className="flex size-7 items-center justify-center rounded-full bg-amber-200 text-xs font-black text-amber-950">
            {user.name.slice(0, 1).toUpperCase()}
          </span>
          <span>Account</span>
        </summary>
        <div className="absolute right-0 z-20 mt-3 w-56 rounded-3xl border border-amber-100 bg-white p-3 text-amber-950 shadow-xl">
          <div className="px-3 py-2">
            <p className="truncate text-sm font-black">{user.name}</p>
            <p className="mt-1 truncate text-xs font-semibold text-amber-700">
              {user.email}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void logout()}
            className="mt-2 w-full rounded-2xl px-3 py-2 text-left text-sm font-bold text-amber-700 transition-colors hover:bg-amber-50 hover:text-amber-950"
            disabled={isLoading}
            aria-label={`Sign out ${user.name}`}
          >
            {isLoading ? "Signing out..." : "Sign out"}
          </button>
        </div>
      </details>
    );
  }

  return (
    <button
      type="button"
      onClick={() => void login()}
      className={buttonClassNames[variant]}
      disabled={isLoading}
    >
      {isLoading ? "Signing in..." : "Sign in with Google"}
    </button>
  );
}
