"use client";

import { useEffect } from "react";
import { getOidcUserManager } from "@/features/auth/lib/oidcClient";

export default function AuthLogoutPage() {
  useEffect(() => {
    getOidcUserManager()
      .removeUser()
      .finally(() => {
        window.location.replace("/");
      });
  }, []);

  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="max-w-md rounded-3xl border border-amber-100 bg-white p-8 text-center shadow-sm">
        <h1 className="text-2xl font-bold text-amber-950">Signing you out</h1>
        <p className="mt-4 text-sm text-stone-600">
          Clearing your local session...
        </p>
      </div>
    </main>
  );
}
