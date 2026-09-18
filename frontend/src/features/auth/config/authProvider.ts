export type AuthProviderName = "mock" | "google" | "cognito";

export function getAuthProvider(): AuthProviderName {
  const provider = process.env.AUTH_PROVIDER;

  if (provider === "mock" || provider === "google" || provider === "cognito") {
    return provider;
  }

  return "mock";
}
