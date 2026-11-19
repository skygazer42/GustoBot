import { computed, onScopeDispose, reactive } from "vue";
import axios from "axios";
import {
  createMessageId,
  parseChatResponse,
  parseUploadResponse,
  type ChatRequest,
  type ChatState
} from "../lib/chat";

const MAX_MESSAGE_LENGTH = 4000;
const API_MESSAGE_LIMIT = 5000;
const REQUEST_TIMEOUT_MS = 120_000;

export function useChat(recipeContext: string | (() => string) = "") {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || "";
  const state = reactive<ChatState>({
    isTyping: false,
    isUploading: false,
    sessionId: "",
    userInput: "",
    messages: [],
    uploadStatus: "",
    attachedFilePath: "",
    attachedFileName: "",
    error: ""
  });
  const isBusy = computed(() => state.isTyping || state.isUploading);
  let chatController: AbortController | null = null;
  let uploadController: AbortController | null = null;
  let disposed = false;
  let lastSubmission: { messageId: string; content: string; filePath: string } | null = null;

  function invalidateRequests(): void {
    const previousChat = chatController;
    const previousUpload = uploadController;
    chatController = null;
    uploadController = null;
    previousChat?.abort();
    previousUpload?.abort();
  }

  function resetSession(): void {
    invalidateRequests();
    lastSubmission = null;
    state.isTyping = false;
    state.isUploading = false;
    state.sessionId = "";
    state.userInput = "";
    state.messages = [];
    state.uploadStatus = "";
    state.attachedFilePath = "";
    state.attachedFileName = "";
    state.error = "";
  }

  function addQuestion(prompt: string): void {
    if (disposed || prompt.trim().length === 0 || state.userInput.includes(prompt)) {
      return;
    }
    const draft = state.userInput.trim().length === 0 ? prompt : `${state.userInput}\n${prompt}`;
    if (draft.length > MAX_MESSAGE_LENGTH) {
      state.error = "问题最多 4000 字，已保留原文，请缩短后再添加。";
      return;
    }
    state.userInput = draft;
    state.error = "";
  }

  async function sendMessage(): Promise<void> {
    const submittedInput = state.userInput;
    const message = submittedInput.trim();
    if (disposed || isBusy.value || message.length === 0) {
      return;
    }
    if (submittedInput.length > MAX_MESSAGE_LENGTH) {
      state.error = "问题最多 4000 字，已保留原文，请缩短后再发送。";
      return;
    }
    const currentRecipeContext = typeof recipeContext === "function" ? recipeContext() : recipeContext;
    const requestMessage = currentRecipeContext.trim().length > 0
      ? `当前正在阅读的食谱：\n${currentRecipeContext}\n\n我的问题：${message}`
      : message;
    if (requestMessage.length > API_MESSAGE_LIMIT) {
      state.error = "问题与当前食谱内容较长，请缩短问题后再发送。";
      return;
    }

    const filePath = state.attachedFilePath;
    let userMessage = lastSubmission?.content === message && lastSubmission.filePath === filePath
      ? state.messages.find((entry) => entry.id === lastSubmission?.messageId)
      : undefined;
    if (userMessage === undefined) {
      const messageId = createMessageId();
      state.messages.push({
        id: messageId,
        role: "user",
        content: message,
        delivery: "pending",
        attachmentName: state.attachedFileName || undefined
      });
      userMessage = state.messages[state.messages.length - 1];
      lastSubmission = { messageId, content: message, filePath };
    } else {
      userMessage.delivery = "pending";
    }

    const controller = new AbortController();
    chatController = controller;
    state.isTyping = true;
    state.error = "";
    const chatRequest: ChatRequest = {
      message: requestMessage,
      session_id: state.sessionId || undefined,
      stream: false
    };
    if (filePath.length > 0) {
      chatRequest.file_path = filePath;
      chatRequest.ingest_incremental = true;
    }

    try {
      const { data: chatResponse } = await axios.post<unknown>(`${apiBaseUrl}/api/v1/chat/`, chatRequest, {
        signal: controller.signal,
        timeout: REQUEST_TIMEOUT_MS
      });
      if (disposed || chatController !== controller) {
        return;
      }
      const result = parseChatResponse(chatResponse);
      userMessage.delivery = "sent";
      state.messages.push(result.message);
      state.sessionId = result.sessionId;
      lastSubmission = null;
      if (state.userInput === submittedInput) {
        state.userInput = "";
      }
      if (state.attachedFilePath === filePath) {
        state.attachedFilePath = "";
        state.attachedFileName = "";
        state.uploadStatus = "";
      }
    } catch {
      if (!disposed && chatController === controller) {
        userMessage.delivery = "failed";
        state.error = "请求出错了，请稍后重试。你的问题与附件已保留。";
      }
    } finally {
      if (!disposed && chatController === controller) {
        chatController = null;
        state.isTyping = false;
      }
    }
  }

  async function onFileSelected(event: Event): Promise<void> {
    const fileInput = event.target;
    if (disposed || isBusy.value || !(fileInput instanceof HTMLInputElement)) {
      return;
    }
    const selectedFile = fileInput.files?.[0];
    if (!selectedFile) {
      return;
    }

    const controller = new AbortController();
    uploadController = controller;
    state.isUploading = true;
    state.uploadStatus = "正在上传...";
    state.error = "";
    fileInput.value = "";
    try {
      const uploadFormData = new FormData();
      uploadFormData.append("file", selectedFile);
      const { data: uploadResponse } = await axios.post<unknown>(`${apiBaseUrl}/api/v1/upload/file`, uploadFormData, {
        signal: controller.signal,
        timeout: REQUEST_TIMEOUT_MS
      });
      if (disposed || uploadController !== controller) {
        return;
      }
      const uploadedFile = parseUploadResponse(uploadResponse, selectedFile.name);
      state.attachedFilePath = uploadedFile.path;
      state.attachedFileName = uploadedFile.name;
      state.uploadStatus = `已上传：${uploadedFile.name}`;
    } catch {
      if (!disposed && uploadController === controller) {
        state.error = "上传失败，请重试。";
        state.uploadStatus = state.attachedFileName.length > 0 ? `已上传：${state.attachedFileName}` : "";
      }
    } finally {
      if (!disposed && uploadController === controller) {
        uploadController = null;
        state.isUploading = false;
      }
    }
  }

  function removeAttachment(): void {
    const previousUpload = uploadController;
    uploadController = null;
    previousUpload?.abort();
    state.isUploading = false;
    state.attachedFilePath = "";
    state.attachedFileName = "";
    state.uploadStatus = "";
  }

  onScopeDispose(() => {
    disposed = true;
    invalidateRequests();
  });

  return {
    state,
    isBusy,
    sendMessage,
    addQuestion,
    resetSession,
    onFileSelected,
    removeAttachment
  };
}
