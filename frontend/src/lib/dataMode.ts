export type DataMode = "json" | "mock" | "api";

export function getDataMode(): DataMode {
  const mode = process.env.NEXT_PUBLIC_DATA_MODE;

  if (mode === "json" || mode === "mock" || mode === "api") {
    return mode;
  }

  return "json";
}
