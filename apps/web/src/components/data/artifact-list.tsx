"use client";

import { ArtifactCard } from "@/components/data/artifact-card";
import type { ArtifactView } from "@/lib/api";

interface ArtifactListProps {
  artifacts: readonly ArtifactView[];
  onView: (artifact: ArtifactView) => void;
  onDownload: (artifact: ArtifactView) => void;
}

/**
 * The last query of a run is the one the answer is built on, so it stays open. Earlier queries
 * (refined, superseded or complementary) stay available but collapsed, so a first attempt
 * never reads as the result.
 */
export function ArtifactList({ artifacts, onView, onDownload }: ArtifactListProps) {
  if (artifacts.length === 0) return null;
  const earlier = artifacts.slice(0, -1);
  const final = artifacts[artifacts.length - 1];
  return (
    <>
      {earlier.length > 0 && (
        <details className="mt-3 rounded-lg border border-dashed border-neutral-300 px-3 py-2 dark:border-neutral-700">
          <summary className="cursor-pointer text-xs text-neutral-500">
            Earlier {earlier.length === 1 ? "query" : `${earlier.length} queries`} in this answer
          </summary>
          {earlier.map((a) => (
            <ArtifactCard key={a.artifact_id} artifact={a} onViewAll={onView} onDownload={onDownload} />
          ))}
        </details>
      )}
      <ArtifactCard artifact={final} onViewAll={onView} onDownload={onDownload} />
    </>
  );
}
