import { useState } from "react";
import "./App.css";
import {
  accept as acceptDraft,
  generate,
  messageOf,
  retryGeneration,
  uploadCoverLetter,
  uploadCv,
  uploadJobDescription,
  type AcceptResponse,
  type GenerateResponse,
} from "./api";
import { DoneScreen } from "./components/DoneScreen";
import { ReviewScreen } from "./components/ReviewScreen";
import { UploadScreen, type UploadData } from "./components/UploadScreen";

type Screen = "upload" | "generating" | "generate-error" | "review" | "done";

interface FieldErrors {
  cv?: string;
  coverLetter?: string;
  jd?: string;
}

function App() {
  const [screen, setScreen] = useState<Screen>("upload");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [draft, setDraft] = useState<GenerateResponse | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [acceptResult, setAcceptResult] = useState<AcceptResponse | null>(null);

  async function runInitialGeneration(id: string) {
    setScreen("generating");
    setGenerationError(null);
    try {
      const result = await generate(id);
      setDraft(result);
      setScreen("review");
    } catch (err) {
      setGenerationError(messageOf(err));
      setScreen("generate-error");
    }
  }

  async function handleUploadSubmit(data: UploadData) {
    setUploading(true);
    setFieldErrors({});

    let id: string;
    try {
      const cvResult = await uploadCv(data.cv);
      id = cvResult.session_id;
      setSessionId(id);
    } catch (err) {
      setFieldErrors({ cv: messageOf(err) });
      setUploading(false);
      return;
    }

    if (data.coverLetter) {
      try {
        await uploadCoverLetter(id, data.coverLetter);
      } catch (err) {
        setFieldErrors({ coverLetter: messageOf(err) });
        setUploading(false);
        return;
      }
    }

    try {
      await uploadJobDescription(id, data.jd);
    } catch (err) {
      setFieldErrors({ jd: messageOf(err) });
      setUploading(false);
      return;
    }

    setUploading(false);
    await runInitialGeneration(id);
  }

  async function handleRetryAfterFailure() {
    if (!sessionId) return;
    await runInitialGeneration(sessionId);
  }

  async function handleRetry() {
    if (!sessionId) return;
    setRetrying(true);
    setAcceptError(null);
    try {
      const result = await retryGeneration(sessionId);
      setDraft(result);
    } catch (err) {
      setGenerationError(messageOf(err));
      setScreen("generate-error");
    } finally {
      setRetrying(false);
    }
  }

  async function handleAccept() {
    if (!sessionId || !draft) return;
    setAccepting(true);
    setAcceptError(null);
    try {
      const result = await acceptDraft(sessionId, draft.draft_id);
      setAcceptResult(result);
      setScreen("done");
    } catch (err) {
      setAcceptError(messageOf(err));
    } finally {
      setAccepting(false);
    }
  }

  function handleStartOver() {
    setScreen("upload");
    setSessionId(null);
    setFieldErrors({});
    setGenerationError(null);
    setDraft(null);
    setAcceptError(null);
    setAcceptResult(null);
  }

  return (
    <main>
      <h1>CVGen</h1>

      {screen === "upload" && (
        <UploadScreen onSubmit={handleUploadSubmit} submitting={uploading} errors={fieldErrors} />
      )}

      {screen === "generating" && <p className="notice">Generating your tailored draft…</p>}

      {screen === "generate-error" && (
        <div className="generate-error">
          <p className="field-error">{generationError}</p>
          <button type="button" onClick={handleRetryAfterFailure}>
            Retry
          </button>
        </div>
      )}

      {screen === "review" && draft && (
        <ReviewScreen
          draft={draft}
          onRetry={handleRetry}
          onAccept={handleAccept}
          retrying={retrying}
          accepting={accepting}
          acceptError={acceptError}
        />
      )}

      {screen === "done" && sessionId && acceptResult && (
        <DoneScreen sessionId={sessionId} result={acceptResult} onStartOver={handleStartOver} />
      )}
    </main>
  );
}

export default App;
