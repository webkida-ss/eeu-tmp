"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AuthContext } from "../hooks/useAuth";
import type { AuthProviderName } from "../config/authProvider";
import type { AuthContextValue, AuthUser } from "../types/auth";
import {
  buildCognitoLogoutUrl,
  getCurrentOidcUser,
  getOidcUserManager,
} from "../lib/oidcClient";
import { getBackendAuthSession } from "../repositories/authSessionRepository";

type AuthProviderProps = {
  children: ReactNode;
  provider: AuthProviderName;
};

const mockUser: AuthUser = {
  id: "0194fd38-7c2e-7a5a-8f2b-28b5d08a9f31",
  name: "Example User",
  email: "user@example.com",
  avatarUrl: "https://placehold.co/96x96/fbbf24/451a03?text=S",
};

export function AuthProvider({ children, provider }: AuthProviderProps) {
  const usesOidc = provider === "cognito" || provider === "google";
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(usesOidc);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!usesOidc) {
      return;
    }

    let isMounted = true;

    getCurrentOidcUser()
      .then(async (oidcUser) => {
        if (!isMounted || !oidcUser) {
          return;
        }

        const session = await getBackendAuthSession(oidcUser.access_token);

        if (!isMounted || !session) {
          setUser(null);
          return;
        }

        setUser({
          id: session.appUserId,
          name:
            oidcUser.profile.name ??
            session.email ??
            oidcUser.profile.email ??
            session.cognitoSub,
          email: session.email,
          avatarUrl: "",
        });
      })
      .catch((source: unknown) => {
        if (isMounted) {
          setError(source instanceof Error ? source.message : "Failed to load session.");
        }
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [usesOidc]);

  const value = useMemo<AuthContextValue>(
    () => ({
      provider,
      user,
      status: isLoading ? "loading" : user ? "authenticated" : "unauthenticated",
      error,
      login: async () => {
        setError(null);
        setIsLoading(true);

        try {
          if (provider === "mock") {
            setUser(mockUser);
            return;
          }

          await getOidcUserManager().signinRedirect({
            state: { returnUrl: window.location.pathname },
          });
        } finally {
          setIsLoading(false);
        }
      },
      logout: async () => {
        setError(null);
        if (usesOidc) {
          await getOidcUserManager().removeUser();
          window.location.assign(buildCognitoLogoutUrl());
          return;
        }

        setUser(null);
      },
    }),
    [error, isLoading, provider, user, usesOidc],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
