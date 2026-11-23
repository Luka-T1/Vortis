import { streamChat } from './sse';
import { generateId, useAppStore } from './store';
import type { ChatMessage, ToolCallInfo } from '../types';

export type ToolOutcome = 'done' | 'unverified' | 'failed' | 'running';

export interface HudToolCall {
  id: string;
  tool: string;
  outcome: ToolOutcome;
  latency?: number;
  at: number;
}

export interface AskHandlers {
  onDelta?: (fullText: string) => void;
  onTool?: (call: HudToolCall) => void;
  onPhase?: (phase: 'thinking' | 'generating' | 'tool') => void;
}

export const HUD_HISTORY_LIMIT = 10;

export const HUD_SYSTEM_PROMPT =
  'Ti si Jarvis, lični asistent korisnika. Odgovaraj na jeziku na kom je pitanje postavljeno (srpski latinicom ili engleski). ' +
  'Budi kratak i jasan: najviše tri do četiri rečenice, osim ako korisnik traži detalje. ' +
  'Odgovori se često izgovaraju naglas, zato izbegavaj tabele i dugačke liste.';

export async function askJarvis(
  text: string,
  handlers: AskHandlers = {},
  signal?: AbortSignal,
): Promise<string> {
  const store = useAppStore.getState();
  const model = store.selectedModel;
  if (!model) throw new Error('Nije izabran model (Podešavanja ili ⌘K).');

  let convId = store.activeId;
  if (!convId) convId = store.createConversation(model);
  const userMsg: ChatMessage = { id: generateId(), role: 'user', content: text, timestamp: Date.now() };
  store.addMessage(convId, userMsg);
  const history = [
    { role: 'system' as const, content: HUD_SYSTEM_PROMPT },
    ...useAppStore
      .getState()
      .messages.slice(-HUD_HISTORY_LIMIT)
      .map((m) => ({ role: m.role, content: m.content })),
  ];
  store.addMessage(convId, { id: generateId(), role: 'assistant', content: '', timestamp: Date.now() });

  const { temperature, maxTokens } = store.settings;
  let content = '';
  const calls: ToolCallInfo[] = [];
  handlers.onPhase?.('thinking');
  try {
    for await (const ev of streamChat(
      { model, messages: history, stream: true, temperature, max_tokens: maxTokens },
      signal,
    )) {
      if (ev.event === 'tool_call_start' || ev.event === 'tool_call_end') {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(ev.data);
        } catch {}
        const tool = String(data.tool ?? 'tool');
        if (ev.event === 'tool_call_start') {
          handlers.onPhase?.('tool');
          const call: ToolCallInfo = { id: generateId(), tool, arguments: String(data.arguments ?? ''), status: 'running' };
          calls.push(call);
          handlers.onTool?.({ id: call.id, tool, outcome: 'running', at: Date.now() });
        } else {
          const call = calls.find((c) => c.tool === tool && c.status === 'running');
          const outcome = (data.outcome as ToolOutcome) || (data.success ? 'done' : 'failed');
          if (call) {
            call.status = data.success ? 'success' : 'error';
            call.result = String(data.result ?? '');
            call.latency = Number(data.latency ?? 0);
            handlers.onTool?.({ id: call.id, tool, outcome, latency: call.latency, at: Date.now() });
          }
        }
        useAppStore.getState().updateLastAssistant(convId, content, [...calls]);
        continue;
      }
      try {
        const data = JSON.parse(ev.data);
        const delta = data.choices?.[0]?.delta?.content;
        if (delta) {
          if (!content) handlers.onPhase?.('generating');
          content += delta;
          handlers.onDelta?.(content);
        }
        if (data.choices?.[0]?.finish_reason === 'stop') break;
      } catch {}
    }
  } finally {
    useAppStore
      .getState()
      .updateLastAssistant(convId, content || '(bez odgovora)', calls.length ? calls : undefined);
  }
  return content;
}
