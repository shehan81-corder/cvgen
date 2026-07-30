import type { GenerateResponse } from "../api";
import { AtsScoreBadge } from "./AtsScoreBadge";
import { DocumentPreview } from "./DocumentPreview";

interface ReviewScreenProps {
  draft: GenerateResponse;
  onRetry: () => void;
  onAccept: () => void;
  retrying: boolean;
  accepting: boolean;
  acceptError: string | null;
}

export function ReviewScreen({
  draft,
  onRetry,
  onAccept,
  retrying,
  accepting,
  acceptError,
}: ReviewScreenProps) {
  const busy = retrying || accepting;

  return (
    <div className="review-screen">
      {draft.low_confidence && (
        <p className="notice">
          The model didn't find much worth changing in this draft. You can still retry for a
          different attempt.
        </p>
      )}

      <div className="ats-scores">
        <AtsScoreBadge label="CV" score={draft.ats.cv} />
        {draft.ats.cover_letter && (
          <AtsScoreBadge label="Cover letter" score={draft.ats.cover_letter} />
        )}
      </div>

      <DocumentPreview title="CV" blocks={draft.cv_preview} />
      {draft.cover_letter_preview && (
        <DocumentPreview title="Cover letter" blocks={draft.cover_letter_preview} />
      )}

      {acceptError && <p className="field-error">{acceptError}</p>}

      <div className="review-actions">
        <button type="button" onClick={onRetry} disabled={busy}>
          {retrying ? "Retrying…" : "Retry"}
        </button>
        <button type="button" onClick={onAccept} disabled={busy}>
          {accepting ? "Saving…" : "Generate"}
        </button>
      </div>
    </div>
  );
}
