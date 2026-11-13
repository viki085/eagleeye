"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";

import { ApiClient } from "@/lib/api";
import { tokenWhenReady } from "@/lib/auth-token";

export function useApi(): ApiClient {
  const { getToken, userId } = useAuth();
  // userId in the deps: when the session arrives (or the user changes) the client changes, so
  // every effect keyed on `api` reloads with the right identity.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- userId is a deliberate refresh key
  return useMemo(() => new ApiClient(() => tokenWhenReady(() => getToken())), [getToken, userId]);
}
