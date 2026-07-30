import { useState } from "react";

export interface UploadData {
  cv: File;
  coverLetter: File | null;
  jd: { text: string } | { file: File };
}

interface FieldErrors {
  cv?: string;
  coverLetter?: string;
  jd?: string;
}

interface UploadScreenProps {
  onSubmit: (data: UploadData) => void;
  submitting: boolean;
  errors: FieldErrors;
}

type JdMode = "text" | "file";

function isDocx(file: File): boolean {
  return file.name.toLowerCase().endsWith(".docx");
}

export function UploadScreen({ onSubmit, submitting, errors }: UploadScreenProps) {
  const [cvFile, setCvFile] = useState<File | null>(null);
  const [coverLetterFile, setCoverLetterFile] = useState<File | null>(null);
  const [jdMode, setJdMode] = useState<JdMode>("text");
  const [jdText, setJdText] = useState("");
  const [jdFile, setJdFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const cvExtensionError =
    cvFile && !isDocx(cvFile)
      ? "Please upload the Word (.docx) version of your CV — PDF can't preserve exact formatting."
      : null;
  const coverLetterExtensionError =
    coverLetterFile && !isDocx(coverLetterFile)
      ? "Please upload the Word (.docx) version of your cover letter — PDF can't preserve exact formatting."
      : null;

  const canSubmit =
    cvFile !== null &&
    isDocx(cvFile) &&
    (coverLetterFile === null || isDocx(coverLetterFile)) &&
    (jdMode === "text" ? jdText.trim().length > 0 : jdFile !== null) &&
    !submitting;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLocalError(null);

    if (!cvFile) {
      setLocalError("Please select your CV.");
      return;
    }
    if (!isDocx(cvFile)) {
      setLocalError(
        "Please upload the Word (.docx) version of your CV — PDF can't preserve exact formatting."
      );
      return;
    }
    if (coverLetterFile && !isDocx(coverLetterFile)) {
      setLocalError(
        "Please upload the Word (.docx) version of your cover letter — PDF can't preserve exact formatting."
      );
      return;
    }
    if (jdMode === "text" && jdText.trim().length === 0) {
      setLocalError("Please paste the job description, or switch to uploading a file.");
      return;
    }
    if (jdMode === "file" && !jdFile) {
      setLocalError("Please select a job description file, or switch to pasting text.");
      return;
    }

    onSubmit({
      cv: cvFile,
      coverLetter: coverLetterFile,
      jd: jdMode === "text" ? { text: jdText } : { file: jdFile as File },
    });
  }

  return (
    <form className="upload-screen" onSubmit={handleSubmit}>
      <section className="upload-field">
        <label htmlFor="cv-input">CV (.docx) — required</label>
        <input
          id="cv-input"
          type="file"
          accept=".docx"
          onChange={(e) => setCvFile(e.target.files?.[0] ?? null)}
        />
        {(cvExtensionError || errors.cv) && (
          <p className="field-error">{cvExtensionError || errors.cv}</p>
        )}
      </section>

      <section className="upload-field">
        <label htmlFor="cover-letter-input">Cover letter (.docx) — optional</label>
        <input
          id="cover-letter-input"
          type="file"
          accept=".docx"
          onChange={(e) => setCoverLetterFile(e.target.files?.[0] ?? null)}
        />
        {(coverLetterExtensionError || errors.coverLetter) && (
          <p className="field-error">{coverLetterExtensionError || errors.coverLetter}</p>
        )}
      </section>

      <section className="upload-field">
        <label>Job description — required</label>
        <div className="jd-mode-toggle">
          <button
            type="button"
            className={jdMode === "text" ? "toggle-active" : ""}
            onClick={() => setJdMode("text")}
          >
            Paste text
          </button>
          <button
            type="button"
            className={jdMode === "file" ? "toggle-active" : ""}
            onClick={() => setJdMode("file")}
          >
            Upload file (.docx/.pdf)
          </button>
        </div>

        {jdMode === "text" ? (
          <textarea
            rows={8}
            placeholder="Paste the job description here…"
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
          />
        ) : (
          <input
            type="file"
            accept=".docx,.pdf"
            onChange={(e) => setJdFile(e.target.files?.[0] ?? null)}
          />
        )}
        {errors.jd && <p className="field-error">{errors.jd}</p>}
      </section>

      {localError && <p className="field-error">{localError}</p>}

      <button type="submit" disabled={!canSubmit}>
        {submitting ? "Uploading…" : "Generate"}
      </button>
    </form>
  );
}
