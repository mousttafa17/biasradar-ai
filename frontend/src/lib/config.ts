const DEFAULT_API_URL = "http://127.0.0.1:8000";

export function getPublicApiUrl(): string {
  const configured = process.env.NEXT_PUBLIC_BIASRADAR_API_URL?.trim();
  return (configured || DEFAULT_API_URL).replace(/\/$/, "");
}
