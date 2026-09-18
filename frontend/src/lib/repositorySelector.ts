import { getDataMode, type DataMode } from "@/lib/dataMode";

export function selectRepository<T>(repositories: Record<DataMode, T>): T {
  return repositories[getDataMode()];
}
