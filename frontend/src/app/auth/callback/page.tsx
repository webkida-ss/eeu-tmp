"use client";

import { useEffect, useState } from "react";
import { getOidcUserManager } from "@/features/auth/lib/oidcClient";

type CallbackState = {
  status: "loading" | "error";
  message: string;
};

export default function AuthCallbackPage() {
  const [state, setState] = useState<CallbackState>({
    status: "loading",
    message: "Completing sign in...",
  });

  useEffect(() => {
    getOidcUserManager()
      .signinRedirectCallback()
      .then((user) => {
        const returnUrl =
          typeof user.state === "object" &&
          user.state !== null &&
          "returnUrl" in user.state &&
          typeof user.state.returnUrl === "string"
            ? user.state.returnUrl
            : "/";

        window.location.replace(returnUrl);
      })
      .catch((source: unknown) => {
        setState({
          status: "error",
          message:
            source instanceof Error
              ? source.message
              : "Failed to complete sign in.",
        });
      });
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="max-w-md rounded-3xl border border-amber-100 bg-white p-8 text-center shadow-sm">
        <h1 className="text-2xl font-bold text-amber-950">
          {state.status === "loading" ? "Signing you in" : "Sign in failed"}
        </h1>
        <p className="mt-4 text-sm text-stone-600">{state.message}</p>
      </div>
    </main>
  );
}
