import { getAuthSession } from "@/lib/api/generated/sdk.gen";
import type { AuthSession } from "@/lib/api/generated/types.gen";

export async function getBackendAuthSession(
  accessToken: string,
): Promise<AuthSession | null> {
  const baseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    process.env.API_BASE_URL ??
    "http://localhost:18080";

  const response = await getAuthSession({
    baseUrl,
    auth: accessToken,
  });

  if (response.response?.status === 401) {
    return null;
  }

  if (response.error) {
    throw new Error("Failed to fetch auth session.");
  }

  return response.data ?? null;
}
