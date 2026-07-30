import type { AcceptResponse } from "../api";
import { downloadUrl } from "../api";

interface DoneScreenProps {
  sessionId: string;
  result: AcceptResponse;
  onStartOver: () => void;
}

export function DoneScreen({ sessionId, result, onStartOver }: DoneScreenProps) {
  return (
    <div className="done-screen">
      <h2>Done</h2>
      <ul className="download-list">
        <li>
          <a href={downloadUrl(sessionId, "cv")}>Download CV — {result.cv_filename}</a>
        </li>
        {result.cover_letter_filename && (
          <li>
            <a href={downloadUrl(sessionId, "cover-letter")}>
              Download cover letter — {result.cover_letter_filename}
            </a>
          </li>
        )}
      </ul>
      <button type="button" onClick={onStartOver}>
        Start over
      </button>
    </div>
  );
}
