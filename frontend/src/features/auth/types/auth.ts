import type { AuthProviderName } from "../config/authProvider";

export type AuthUser = {
  id: string;
  name: string;
  email: string;
  avatarUrl: string;
};

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export type AuthContextValue = {
  provider: AuthProviderName;
  user: AuthUser | null;
  status: AuthStatus;
  error: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
};
