import type { WebRoute } from "@e2e-dev/web";

export const CHAT_RUN_URL = "**/api/v1/chat/ag-ui";

export function chatRunRequest(route: WebRoute): Record<string, unknown> {
  const { messages, forwardedProps } = JSON.parse(route.request.postData!);
  return { ...forwardedProps, message: messages.at(-1).content };
}

export function fulfillChatRun(route: WebRoute, result: { message: string; session_id: string; [key: string]: unknown }) {
  const { threadId, runId } = JSON.parse(route.request.postData!);
  const messageId = `${runId}-answer`;
  const events = [
    { type: "RUN_STARTED", threadId, runId },
    { type: "STEP_STARTED", stepName: "answering" },
    { type: "TEXT_MESSAGE_START", messageId, role: "assistant" },
    { type: "TEXT_MESSAGE_CONTENT", messageId, delta: result.message },
    { type: "TEXT_MESSAGE_END", messageId },
    { type: "STEP_FINISHED", stepName: "answering" },
    { type: "RUN_FINISHED", threadId, runId, result }
  ];
  return route.fulfill({ contentType: "text/event-stream", body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") });
}
