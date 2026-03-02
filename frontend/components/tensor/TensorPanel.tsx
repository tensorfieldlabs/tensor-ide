import { useState, useRef, useEffect } from "react";
import { api, getSession } from "../../api";
import type { OpenFile } from "../../App";

interface Props {
  openFile: OpenFile | null;
  cwd?: string;
  hidden: boolean;
  onClose?: () => void;
  onFileChanged?: (path: string) => void;
  onAgentFile?: (path: string, content: string) => void;
  onAgentCommand?: (cmd: string, output: string) => void;
  onAgentScreenshot?: (base64: string) => void;
  onAgentUrl?: (url: string) => void;
}

type MessageBlock =
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | { type: "tool_start"; name: string }
  | { type: "tool_end"; name: string; preview: string };

interface Message {
  role: "user" | "peer";
  blocks: MessageBlock[];
}

type ModelEntry = { id: string; provider: string };

const PROVIDER_LABEL: Record<string, string> = {
  claude: "Anthropic",
  gemini: "Google",
  groq: "Groq",
  local_mlx: "Local",
};

function groupModels(models: ModelEntry[]) {
  const groups: Record<string, string[]> = {};
  for (const m of models) {
    const label = PROVIDER_LABEL[m.provider] ?? m.provider;
    (groups[label] ??= []).push(m.id);
  }
  const order = ["Anthropic", "Google", "Groq", "Local"];
  const known = order.filter(l => groups[l]).map(l => ({ label: l, models: groups[l] }));
  const other = Object.keys(groups).filter(l => !order.includes(l));
  return [...known, ...other.map(l => ({ label: l, models: groups[l] }))];
}

function ToolBlock({ name, active, preview }: { name: string; active: boolean; preview?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={`tensor-tool-block ${active ? "active" : "done"}`}
      onClick={() => !active && preview && setOpen(o => !o)}
      style={!active && preview ? { cursor: "pointer" } : undefined}
    >
      <div className="tensor-tool-header">
        <span className="tensor-tool-icon">{active ? "⟳" : "✓"}</span>
        <span className="tensor-tool-name">{name}</span>
        {!active && preview && <span className="tensor-tool-toggle" style={{ marginLeft: "auto", opacity: 0.5 }}>{open ? "▾" : "▸"}</span>}
      </div>
      {open && preview && <pre className="tensor-tool-preview">{preview}</pre>}
    </div>
  );
}

function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let rem = text;
  let k = 0;
  while (rem.length > 0) {
    const ci = rem.indexOf("`");
    const bi = rem.indexOf("**");
    if (ci === -1 && bi === -1) { out.push(rem); break; }
    const first = ci === -1 ? bi : bi === -1 ? ci : Math.min(ci, bi);
    if (first > 0) { out.push(rem.slice(0, first)); rem = rem.slice(first); continue; }
    if (rem.startsWith("**")) {
      const end = rem.indexOf("**", 2);
      if (end === -1) { out.push(rem); break; }
      out.push(<strong key={k++}>{rem.slice(2, end)}</strong>);
      rem = rem.slice(end + 2);
    } else {
      const end = rem.indexOf("`", 1);
      if (end === -1) { out.push(rem); break; }
      out.push(<code key={k++} className="tensor-inline-code">{rem.slice(1, end)}</code>);
      rem = rem.slice(end + 1);
    }
  }
  return out;
}

function Markdown({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  let key = 0;
  const segments = text.split(/(```[\s\S]*?```)/g);
  for (const seg of segments) {
    if (seg.startsWith("```")) {
      const inner = seg.slice(3, -3);
      const nl = inner.indexOf("\n");
      const lang = nl === -1 ? "" : inner.slice(0, nl).trim();
      const code = nl === -1 ? inner : inner.slice(nl + 1);
      parts.push(
        <pre key={key++} className="tensor-code-block">
          {lang && <span className="tensor-code-lang">{lang}</span>}
          <code>{code}</code>
        </pre>
      );
    } else {
      const lines = seg.split("\n");
      for (let i = 0; i < lines.length; i++) {
        if (lines[i] === "") { parts.push(<br key={key++} />); continue; }
        parts.push(<span key={key++}>{renderInline(lines[i])}</span>);
        if (i < lines.length - 1) parts.push(<br key={key++} />);
      }
    }
  }
  return <>{parts}</>;
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tensor-thinking-block" onClick={() => setOpen(o => !o)}>
      <div className="tensor-thinking-header">
        <span className="tensor-thinking-toggle">{open ? "▾" : "▸"}</span>
        <span className="tensor-thinking-label">...</span>
      </div>
      {open && <div className="tensor-thinking-body">{text}</div>}
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  if (msg.role === "user") {
    const text = msg.blocks.filter(b => b.type === "text").map(b => (b as any).text).join("");
    return (
      <div className="tensor-msg user">
        <div className="tensor-bubble">{text}</div>
      </div>
    );
  }
  return (
    <div className="tensor-msg peer">
      {msg.blocks.map((block, i) => {
        if (block.type === "text" && block.text) return <div key={i} className="tensor-bubble"><Markdown text={block.text} /></div>;
        if (block.type === "thinking") return <ThinkingBlock key={i} text={block.text} />;
        if (block.type === "tool_start") return <ToolBlock key={i} name={block.name} active={true} />;
        if (block.type === "tool_end") return <ToolBlock key={i} name={block.name} active={false} preview={block.preview} />;
        return null;
      })}
    </div>
  );
}

const FILE_TOOLS = new Set(["write_file", "edit_file", "append_file"]);

export function TensorPanel({ openFile, hidden, onClose, onFileChanged, onAgentFile, onAgentCommand, onAgentScreenshot, onAgentUrl }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [selectedModel, setSelectedModel] = useState("claude-sonnet-4-6");
  const [availableModels, setAvailableModels] = useState<ModelEntry[]>([]);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const [convId, setConvId] = useState(() => `conv-${Date.now()}`);
  const [convList, setConvList] = useState<string[]>([]);
  const [convListOpen, setConvListOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const pendingToolArgs = useRef<Record<string, unknown>>({});

  // Load models
  useEffect(() => {
    api.getModels().then((res) => {
      if (res.models?.length) {
        setAvailableModels(res.models);
        setSelectedModel(m => res.models.find(e => e.id === m) ? m : res.models[0].id);
      }
    }).catch(console.error);
  }, []);

  // Load conversation list
  useEffect(() => {
    api.listConversations().then(res => setConvList(res.conversations || [])).catch(console.error);
  }, []);

  // Load conversation history when switching
  useEffect(() => {
    api.getConversation(convId).then(res => {
      const msgs: Message[] = res.turns.map(t => ({
        role: t.role === "user" ? "user" as const : "peer" as const,
        blocks: [{ type: "text" as const, text: t.text }],
      }));
      setMessages(msgs);
    }).catch(() => setMessages([]));
  }, [convId]);

  // Close model picker on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setModelPickerOpen(false);
      }
    }
    if (modelPickerOpen) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [modelPickerOpen]);

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  useEffect(() => { scrollToBottom(); }, [messages, isThinking]);

  function handleNewConversation() {
    const id = `conv-${Date.now()}`;
    setConvId(id);
    setMessages([]);
    setConvListOpen(false);
    // Will be persisted on first message
  }

  function handleSwitchConversation(id: string) {
    setConvId(id);
    setConvListOpen(false);
  }

  async function handleDeleteConversation(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    await api.deleteConversation(id);
    setConvList(prev => prev.filter(c => c !== id));
    if (convId === id) {
      setConvId("main");
      setMessages([]);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || isThinking) return;

    setInput("");
    const userMsg: Message = { role: "user", blocks: [{ type: "text", text }] };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setIsThinking(true);

    let prompt = text;
    if (openFile) {
      prompt = `Context file: ${openFile.path}\n\`\`\`\n${openFile.content}\n\`\`\`\n\nUser Question: ${text}`;
    }

    const useCloud = !selectedModel.startsWith("local/");
    const model = selectedModel;

    setMessages([...newMessages, { role: "peer", blocks: [] }]);

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      const res = await fetch("/api/generate/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...api.authHeaders() },
        body: JSON.stringify({
          prompt, max_tokens: 4096, temperature: 0.0,
          use_cloud: useCloud, model, conversation_id: convId,
        }),
        signal: controller.signal,
      });

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No reader");

      const decoder = new TextDecoder();
      let buffer = "";
      let currentBlocks: MessageBlock[] = [];
      let currentText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6);
          if (payload === "[DONE]") break;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.delta) {
              currentText += parsed.delta;
              const blocks = [...currentBlocks];
              const last = blocks[blocks.length - 1];
              if (last && last.type === "text") blocks[blocks.length - 1] = { type: "text", text: currentText };
              else blocks.push({ type: "text", text: currentText });
              currentBlocks = blocks;
              setMessages([...newMessages, { role: "peer", blocks: [...currentBlocks] }]);
            }
            if (parsed.thinking_delta) {
              currentText = "";
              const blocks = [...currentBlocks];
              const last = blocks[blocks.length - 1];
              if (last && last.type === "thinking") blocks[blocks.length - 1] = { type: "thinking", text: last.text + parsed.thinking_delta };
              else blocks.push({ type: "thinking", text: parsed.thinking_delta });
              currentBlocks = blocks;
              setMessages([...newMessages, { role: "peer", blocks: [...currentBlocks] }]);
            }
            if (parsed.tool_start) {
              currentText = "";
              pendingToolArgs.current = parsed.args || {};
              currentBlocks = [...currentBlocks, { type: "tool_start", name: parsed.tool_start }];
              setMessages([...newMessages, { role: "peer", blocks: [...currentBlocks] }]);
            }
            if (parsed.tool_end) {
              currentBlocks = currentBlocks.map(b =>
                b.type === "tool_start" && b.name === parsed.tool_end
                  ? { type: "tool_end" as const, name: parsed.tool_end, preview: parsed.preview || "" }
                  : b
              );
              currentText = "";
              setMessages([...newMessages, { role: "peer", blocks: [...currentBlocks] }]);
              const toolPath = (parsed.path || pendingToolArgs.current?.path) as string | undefined;
              // Refresh editor if AI wrote/edited the open file
              if (FILE_TOOLS.has(parsed.tool_end) && onFileChanged && toolPath) {
                onFileChanged(toolPath);
              }
              // Feed agent view
              if (toolPath) {
                if (FILE_TOOLS.has(parsed.tool_end) || parsed.tool_end === "read_file") {
                  fetch("/api/read_file", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", ...api.authHeaders() },
                    body: JSON.stringify({ path: toolPath }),
                  }).then(r => r.json()).then(d => {
                    if (d.content !== undefined) onAgentFile?.(toolPath, d.content);
                  }).catch(() => {});
                }
              }
              if (parsed.tool_end === "run_shell") {
                const cmd = (pendingToolArgs.current?.command as string) ?? "";
                onAgentCommand?.(cmd, parsed.preview || "");
              }
              if (parsed.tool_end === "browser_screenshot" && parsed.preview) {
                const raw = parsed.preview as string;
                const b64 = raw.startsWith("IMAGE:") ? raw.slice(6) : raw;
                if (b64.length > 100) onAgentScreenshot?.(b64);
              }
              if (parsed.tool_end === "browser_goto") {
                const url = (pendingToolArgs.current?.url as string) ?? "";
                if (url) onAgentUrl?.(url);
              }
            }
          } catch { /* skip */ }
        }
      }

      if (currentBlocks.length === 0) {
        setMessages([...newMessages, { role: "peer", blocks: [{ type: "text", text: "Something went wrong." }] }]);
      }

      // Refresh conv list
      api.listConversations().then(res => setConvList(res.conversations || [])).catch(() => {});
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setMessages([...newMessages, { role: "peer", blocks: [{ type: "text", text: "Lost connection. Try again?" }] }]);
    } finally {
      abortRef.current = null;
      setIsThinking(false);
    }
  }

  return (
    <div className={`tensor-panel${hidden ? " tensor-hidden" : ""}`}>
      {/* Header: conversation switcher + close */}
      <div className="tensor-header">
        <div className="tensor-header-top">
          <div className="tensor-conv-switcher">
            <button className="tensor-conv-btn" onClick={() => setConvListOpen(o => !o)}>
              <span className="tensor-conv-label">{convId === "main" ? "Main" : convId.replace("conv-", "#")}</span>
              <span className="tensor-conv-arrow">{convListOpen ? "\u25B4" : "\u25BE"}</span>
            </button>
            {convListOpen && (
              <div className="tensor-conv-dropdown">
                <button className="tensor-conv-item new" onClick={handleNewConversation}>+ New conversation</button>
                <button className={`tensor-conv-item ${convId === "main" ? "active" : ""}`} onClick={() => handleSwitchConversation("main")}>
                  Main
                </button>
                {convList.filter(c => c !== "main").map(c => (
                  <button key={c} className={`tensor-conv-item ${convId === c ? "active" : ""}`} onClick={() => handleSwitchConversation(c)}>
                    <span>{c.replace("conv-", "#")}</span>
                    <span className="tensor-conv-delete" onClick={(e) => handleDeleteConversation(c, e)}>✕</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <button className="tensor-close" onClick={onClose} title="Close chat">✕</button>
        </div>
      </div>

      {/* Messages */}
      <div className="tensor-content chat">
        <div className="tensor-messages">
          {messages.map((m, i) => <MessageBubble key={i} msg={m} />)}
          {isThinking && (messages.length === 0 || messages[messages.length - 1]?.blocks.length === 0) && (
            <div className="tensor-msg peer">
              <div className="tensor-bubble tensor-thinking">
                <span className="tensor-thinking-dot" />
                <span className="tensor-thinking-dot" />
                <span className="tensor-thinking-dot" />
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area: robot model picker + textarea + send */}
      <div className="tensor-input-area" ref={pickerRef}>
        {modelPickerOpen && (
          <div className="tensor-model-dropdown">
            {groupModels(availableModels).map(group => (
              <div key={group.label} className="tensor-model-group">
                <div className="tensor-model-group-label">{group.label}</div>
                <div className="tensor-model-options-grid">
                  {group.models.map(m => (
                    <button
                      key={m}
                      className={`tensor-model-option ${m === selectedModel ? "active" : ""}`}
                      onClick={() => { setSelectedModel(m); setModelPickerOpen(false); }}
                    >
                      <span className="tensor-model-option-dot" />
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="tensor-model-orb-wrap">
          <button
            className={`tensor-model-orb ${modelPickerOpen ? "open" : ""}`}
            onClick={() => setModelPickerOpen(o => !o)}
            title={selectedModel}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="4" width="16" height="12" rx="2" />
              <circle cx="9" cy="10" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="15" cy="10" r="1.5" fill="currentColor" stroke="none" />
              <line x1="8" y1="16" x2="8" y2="20" />
              <line x1="16" y1="16" x2="16" y2="20" />
            </svg>
          </button>
        </div>
        <textarea
          className="tensor-textarea"
          placeholder="Message Tensor..."
          rows={1}
          enterKeyHint="send"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
        />
        <button className="tensor-send" onClick={handleSend} disabled={isThinking || !input.trim()}>
          ↑
        </button>
      </div>
    </div>
  );
}
