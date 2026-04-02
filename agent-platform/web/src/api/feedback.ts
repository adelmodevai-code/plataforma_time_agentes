const API_URL = (import.meta as ImportMeta & { env: Record<string, string> }).env?.VITE_API_URL ?? "http://localhost:8080";

interface FeedbackParams {
  sessionId: string;
  messageId: string;
  agent: string;
  rating: "positive" | "negative";
  comment?: string;
}

export async function sendFeedback(params: FeedbackParams): Promise<{ status: string }> {
  try {
    const resp = await fetch(`${API_URL}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: params.sessionId,
        message_id: params.messageId,
        agent: params.agent,
        rating: params.rating,
        comment: params.comment,
      }),
    });
    if (!resp.ok) {
      return { status: "error" };
    }
    return await resp.json();
  } catch {
    return { status: "error" };
  }
}
