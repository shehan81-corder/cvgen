const BASE = "/api";

export interface RunStyle {
  font: string | null;
  size: number | null;
  color: string | null;
  bold: boolean | null;
  italic: boolean | null;
  underline: boolean | null;
}

export interface PreviewBlock {
  id: string;
  group_key: string;
  original_text: string;
  tailored_text: string;
  style_name: string | null;
  run_style: RunStyle;
  section: string | null;
  editable: boolean | null;
  changed: boolean;
}

export interface AtsScore {
  original: number;
  tailored: number;
}

export interface GenerateResponse {
  session_id: string;
  draft_id: number;
  low_confidence: boolean;
  ats: { cv: AtsScore; cover_letter?: AtsScore };
  cv_preview: PreviewBlock[];
  cover_letter_preview: PreviewBlock[] | null;
}

export interface AcceptResponse {
  session_id: string;
  draft_id: number;
  cv_filename: string;
  cover_letter_filename?: string;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response wasn't JSON; fall back to statusText
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export async function uploadCv(file: File): Promise<{ session_id: string; block_count: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/sessions/cv`, { method: "POST", body: form });
  return handleResponse(res);
}

export async function uploadCoverLetter(
  sessionId: string,
  file: File
): Promise<{ session_id: string; block_count: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/sessions/${sessionId}/cover-letter`, {
    method: "POST",
    body: form,
  });
  return handleResponse(res);
}

export async function uploadJobDescription(
  sessionId: string,
  input: { text: string } | { file: File }
): Promise<{ session_id: string; character_count: number }> {
  const form = new FormData();
  if ("file" in input) {
    form.append("file", input.file);
  } else {
    form.append("text", input.text);
  }
  const res = await fetch(`${BASE}/sessions/${sessionId}/job-description`, {
    method: "POST",
    body: form,
  });
  return handleResponse(res);
}

export async function generate(sessionId: string): Promise<GenerateResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/generate`, { method: "POST" });
  return handleResponse(res);
}

export async function retryGeneration(sessionId: string): Promise<GenerateResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/retry`, { method: "POST" });
  return handleResponse(res);
}

export async function accept(sessionId: string, draftId: number): Promise<AcceptResponse> {
  const res = await fetch(`${BASE}/sessions/${sessionId}/accept?draft_id=${draftId}`, {
    method: "POST",
  });
  return handleResponse(res);
}

export function downloadUrl(sessionId: string, document: "cv" | "cover-letter"): string {
  return `${BASE}/sessions/${sessionId}/download/${document}`;
}

export function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong. Please try again.";
}
