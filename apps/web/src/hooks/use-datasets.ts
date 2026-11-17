"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiClient, DatasetStatus, DatasetSummary } from "@/lib/api";

const POLL_MS = 2000;
/** Fired on window when a data file is added elsewhere (e.g. a table saved from a source). */
export const DATASETS_CHANGED = "eagleeye:datasets-changed";
const TERMINAL: ReadonlySet<DatasetStatus> = new Set(["READY", "FAILED"]);

export interface DatasetsState {
  datasets: readonly DatasetSummary[];
  uploading: boolean;
  error: string | null;
  upload: (file: File) => Promise<void>;
  remove: (datasetId: string) => Promise<void>;
  clearError: () => void;
}

function message(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** The user's data files; polls while any is still being profiled. */
export function useDatasets(api: ApiClient): DatasetsState {
  const [datasets, setDatasets] = useState<readonly DatasetSummary[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setDatasets(await api.listDatasets());
    } catch (e: unknown) {
      setError(message(e, "Failed to load data files"));
    }
  }, [api]);

  useEffect(() => {
    void refresh();
    const onChanged = () => void refresh();
    window.addEventListener(DATASETS_CHANGED, onChanged);
    return () => window.removeEventListener(DATASETS_CHANGED, onChanged);
  }, [refresh]);

  const processing = useMemo(() => datasets.some((d) => !TERMINAL.has(d.status)), [datasets]);

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setError(null);
      try {
        const ds = await api.uploadDataset(file);
        setDatasets((prev) => [ds, ...prev.filter((d) => d.id !== ds.id)]);
      } catch (e: unknown) {
        setError(message(e, "Upload failed"));
      } finally {
        setUploading(false);
      }
    },
    [api],
  );

  const remove = useCallback(
    async (datasetId: string) => {
      setError(null);
      try {
        await api.deleteDataset(datasetId);
        setDatasets((prev) => prev.filter((d) => d.id !== datasetId));
      } catch (e: unknown) {
        setError(message(e, "Delete failed"));
      }
    },
    [api],
  );

  const clearError = useCallback(() => setError(null), []);

  return { datasets, uploading, error, upload, remove, clearError };
}
