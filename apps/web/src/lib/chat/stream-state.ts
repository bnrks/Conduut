import type { ChatStreamEvent } from "@/lib/chat/sse";
import type { AgentStep, MessageAttachment } from "@/types/chat";

export const RECOVERY_ACTION_PREFIX = "__recovery__:";

const DEFAULT_RECOVERY_MESSAGE =
  "Agent tarafında bir sorun oluştu. Baştan tekrar deniyorum…";

export interface AssistantStreamState {
  activeAttemptId?: string;
  content: string;
  thinking: string;
  attachments: MessageAttachment[];
  steps: AgentStep[];
  provider?: string;
  model?: string;
  tier?: string;
  attachmentsRevealed: boolean;
}

export interface AssistantStreamResult {
  state: AssistantStreamState;
  accepted: boolean;
  kind: "update" | "done" | "error" | "recovery" | "ignored";
  activity?: string;
  conversationId?: string;
  errorMessage?: string;
}

export function createAssistantStreamState(): AssistantStreamState {
  return {
    content: "",
    thinking: "",
    attachments: [],
    steps: [],
    attachmentsRevealed: false,
  };
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function cloneSteps(steps: AgentStep[]): AgentStep[] {
  return steps.map((step) =>
    step.kind === "text"
      ? { kind: "text", text: step.text }
      : { kind: "activity", actions: [...step.actions] }
  );
}

function appendText(steps: AgentStep[], text: string): AgentStep[] {
  const next = cloneSteps(steps);
  const last = next[next.length - 1];
  if (last?.kind === "text") {
    last.text += text;
  } else {
    next.push({ kind: "text", text });
  }
  return next;
}

function appendActivity(steps: AgentStep[], action: string): AgentStep[] {
  const next = cloneSteps(steps);
  const last = next[next.length - 1];
  const followsRecovery =
    last?.kind === "activity" &&
    last.actions.some((item) => item.startsWith(RECOVERY_ACTION_PREFIX));
  if (last?.kind === "activity" && !followsRecovery) {
    last.actions.push(action);
  } else {
    next.push({ kind: "activity", actions: [action] });
  }
  return next;
}

function eventAttemptId(event: ChatStreamEvent): string | undefined {
  return stringValue(event.data.attempt_id);
}

function belongsToActiveAttempt(
  state: AssistantStreamState,
  event: ChatStreamEvent
): boolean {
  const attemptId = eventAttemptId(event);
  return !state.activeAttemptId || state.activeAttemptId === attemptId;
}

function withFirstAttempt(
  state: AssistantStreamState,
  event: ChatStreamEvent
): AssistantStreamState {
  if (state.activeAttemptId) return state;
  const attemptId = eventAttemptId(event);
  return attemptId ? { ...state, activeAttemptId: attemptId } : state;
}

export function reduceAssistantStreamEvent(
  current: AssistantStreamState,
  event: ChatStreamEvent
): AssistantStreamResult {
  const conversationId = stringValue(event.data.conversation_id);

  if (event.event === "recovery") {
    const failedAttemptId = stringValue(event.data.failed_attempt_id);
    if (
      current.activeAttemptId &&
      failedAttemptId &&
      current.activeAttemptId !== failedAttemptId
    ) {
      return { state: current, accepted: false, kind: "ignored" };
    }

    const message = stringValue(event.data.message) ?? DEFAULT_RECOVERY_MESSAGE;
    const nextAttemptId = stringValue(event.data.next_attempt_id);
    return {
      state: {
        ...createAssistantStreamState(),
        activeAttemptId: nextAttemptId,
        steps: [
          { kind: "activity", actions: [`${RECOVERY_ACTION_PREFIX}${message}`] },
        ],
      },
      accepted: true,
      kind: "recovery",
      activity: message,
      conversationId,
    };
  }

  if (!belongsToActiveAttempt(current, event)) {
    return { state: current, accepted: false, kind: "ignored" };
  }

  const state = withFirstAttempt(current, event);

  if (event.event === "error") {
    return {
      state,
      accepted: true,
      kind: "error",
      conversationId,
      errorMessage:
        stringValue(event.data.message) ?? "An error occurred. Please try again.",
    };
  }

  if (event.event === "done") {
    return {
      state: {
        ...state,
        provider: stringValue(event.data.provider),
        model: stringValue(event.data.model),
        tier: stringValue(event.data.tier),
        attachmentsRevealed: true,
      },
      accepted: true,
      kind: "done",
      activity: "Finishing the response",
      conversationId,
    };
  }

  if (event.event === "tool_call") {
    const tool = stringValue(event.data.tool);
    if (!tool) return { state, accepted: true, kind: "update", conversationId };
    return {
      state: { ...state, steps: appendActivity(state.steps, tool) },
      accepted: true,
      kind: "update",
      conversationId,
    };
  }

  if (event.event === "token") {
    const text = stringValue(event.data.text);
    if (!text) return { state, accepted: true, kind: "update", conversationId };
    return {
      state: {
        ...state,
        content: state.content + text,
        steps: appendText(state.steps, text),
      },
      accepted: true,
      kind: "update",
      conversationId,
    };
  }

  if (event.event === "thinking") {
    const text = stringValue(event.data.text);
    if (!text) return { state, accepted: true, kind: "update", conversationId };
    return {
      state: { ...state, thinking: state.thinking + text },
      accepted: true,
      kind: "update",
      conversationId,
    };
  }

  if (event.event === "attachment") {
    const type = stringValue(event.data.type) as MessageAttachment["type"] | undefined;
    if (!type) return { state, accepted: true, kind: "update", conversationId };
    return {
      state: {
        ...state,
        attachments: [
          ...state.attachments,
          {
            type,
            data: (event.data.data || {}) as Record<string, unknown>,
          },
        ],
      },
      accepted: true,
      kind: "update",
      conversationId,
    };
  }

  return { state, accepted: false, kind: "ignored" };
}

function withoutRecoverySteps(steps: AgentStep[]): AgentStep[] | undefined {
  const clean = steps.flatMap((step): AgentStep[] => {
    if (step.kind === "text") return [{ kind: "text", text: step.text }];
    const actions = step.actions.filter(
      (action) => !action.startsWith(RECOVERY_ACTION_PREFIX)
    );
    return actions.length > 0 ? [{ kind: "activity", actions }] : [];
  });
  return clean.length > 0 ? clean : undefined;
}

export function assistantStreamFields(
  state: AssistantStreamState,
  { ephemeral = true }: { ephemeral?: boolean } = {}
) {
  const steps = ephemeral
    ? state.steps.length > 0
      ? cloneSteps(state.steps)
      : undefined
    : withoutRecoverySteps(state.steps);
  return {
    content: state.content,
    thinking: ephemeral && state.thinking ? state.thinking : undefined,
    attachments: state.attachmentsRevealed ? [...state.attachments] : [],
    steps,
    provider: state.provider,
    model: state.model,
    tier: state.tier,
  };
}
