"use client";

import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";

let userManager: UserManager | null = null;

export function getOidcUserManager(): UserManager {
  if (userManager) {
    return userManager;
  }

  const authority = process.env.NEXT_PUBLIC_COGNITO_AUTHORITY;
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  const redirectUri =
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ??
    `${window.location.origin}/auth/callback`;
  const postLogoutRedirectUri =
    process.env.NEXT_PUBLIC_COGNITO_POST_LOGOUT_REDIRECT_URI ??
    `${window.location.origin}/auth/logout`;

  if (!authority || !clientId) {
    throw new Error("Cognito OIDC configuration is missing.");
  }

  userManager = new UserManager({
    authority,
    client_id: clientId,
    redirect_uri: redirectUri,
    post_logout_redirect_uri: postLogoutRedirectUri,
    response_type: "code",
    scope: "openid email profile",
    userStore: new WebStorageStateStore({ store: window.sessionStorage }),
  });

  return userManager;
}

export function buildCognitoLogoutUrl(): string {
  const hostedUiBaseUrl = process.env.NEXT_PUBLIC_COGNITO_HOSTED_UI_BASE_URL;
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  const logoutUri =
    process.env.NEXT_PUBLIC_COGNITO_POST_LOGOUT_REDIRECT_URI ??
    `${window.location.origin}/auth/logout`;

  if (!hostedUiBaseUrl || !clientId) {
    throw new Error("Cognito logout configuration is missing.");
  }

  const logoutUrl = new URL("/logout", hostedUiBaseUrl);
  logoutUrl.searchParams.set("client_id", clientId);
  logoutUrl.searchParams.set("logout_uri", logoutUri);

  return logoutUrl.toString();
}

export async function getCurrentOidcUser(): Promise<User | null> {
  const user = await getOidcUserManager().getUser();

  if (!user || user.expired) {
    return null;
  }

  return user;
}
