import axios from "axios";

const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim().replace(
  /\/$/,
  "",
);
const configuredTimeout = Number(
  process.env.NEXT_PUBLIC_API_TIMEOUT_MS ?? "30000",
);

if (!configuredBaseUrl && process.env.NODE_ENV === "production") {
  throw new Error("NEXT_PUBLIC_API_BASE_URL must be configured for production");
}

const timeout =
  Number.isFinite(configuredTimeout) && configuredTimeout > 0
    ? configuredTimeout
    : 30_000;

export const apiClient = axios.create({
  baseURL: configuredBaseUrl || "http://localhost:8000/api/v1",
  headers: {
    Accept: "application/json",
  },
  timeout,
});
