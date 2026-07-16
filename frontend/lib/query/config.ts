export const queryDefaults = {
  retry: 1,
  staleTime: 30_000,
  refetchOnWindowFocus: false,
  refetchOnReconnect: true,
} as const;
