const DEFAULT_API_URL = "http://127.0.0.1:8000";

export function getPublicApiUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BIASRADAR_API_URL?.trim();
  const value = (configured || DEFAULT_API_URL).replace(/\/$/, "");
  const parsed = new URL(value);
  const isLocal = ["localhost", "127.0.0.1", "::1"].includes(parsed.hostname);
  if (
    (parsed.protocol !== "https:" && !(isLocal && parsed.protocol === "http:")) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    parsed.pathname !== "/"
  ) {
    throw new Error("NEXT_PUBLIC_BIASRADAR_API_URL must be a safe service root");
  }
  return value;
}
