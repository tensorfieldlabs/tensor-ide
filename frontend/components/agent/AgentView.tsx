import { useEffect, useRef, useState } from "react";
import type * as MonacoType from "monaco-editor";

export interface AgentState {
  file: { path: string; content: string; lang: string } | null;
  command: { cmd: string; output: string } | null;
  recentFiles: string[];
  screenshot: string | null;   // base64 PNG
  url: string | null;          // last navigated URL
}

type Tab = "code" | "browser";

interface Props {
  state: AgentState;
}

export function AgentView({ state }: Props) {
  const editorContainerRef = useRef<HTMLDivElement>(null);
  const editorInstanceRef = useRef<MonacoType.editor.IStandaloneCodeEditor | null>(null);
  const monacoModuleRef = useRef<typeof MonacoType | null>(null);
  const [shellOpen, setShellOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("code");

  // Auto-switch to browser tab when screenshot arrives
  useEffect(() => {
    if (state.screenshot) setActiveTab("browser");
  }, [state.screenshot]);

  // Auto-switch to code tab when file arrives
  useEffect(() => {
    if (state.file) setActiveTab("code");
  }, [state.file]);

  useEffect(() => {
    const container = editorContainerRef.current;
    if (!container) return;
    let disposed = false;
    let ro: ResizeObserver | null = null;

    (async () => {
      const monaco = await import("monaco-editor");
      if (disposed) return;
      monacoModuleRef.current = monaco;

      monaco.editor.defineTheme("tensor-agent", {
        base: "vs-dark",
        inherit: true,
        rules: [
          { token: "comment", foreground: "6b7280", fontStyle: "italic" },
          { token: "keyword", foreground: "c678dd" },
          { token: "string", foreground: "98c379" },
          { token: "number", foreground: "d19a66" },
          { token: "type", foreground: "e5c07b" },
          { token: "function", foreground: "61afef" },
        ],
        colors: {
          "editor.background": "#00000000",
          "editor.lineHighlightBackground": "#ffffff08",
          "editor.selectionBackground": "#3b82f630",
          "editorGutter.background": "#00000000",
          "editorLineNumber.foreground": "#ffffff33",
          "editorLineNumber.activeForeground": "#ffffff77",
          "editorCursor.foreground": "#a0b4ff88",
        },
      });

      const ed = monaco.editor.create(container, {
        value: "",
        language: "plaintext",
        theme: "tensor-agent",
        readOnly: true,
        minimap: { enabled: false },
        lineNumbers: "on",
        scrollBeyondLastLine: false,
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 13,
        lineHeight: 20,
        wordWrap: "on",
        renderLineHighlight: "none",
        overviewRulerLanes: 0,
        scrollbar: { vertical: "auto", horizontal: "auto" },
      });

      editorInstanceRef.current = ed;

      ro = new ResizeObserver(() => ed.layout());
      ro.observe(container);
      requestAnimationFrame(() => ed.layout());
    })();

    return () => {
      disposed = true;
      ro?.disconnect();
      editorInstanceRef.current?.dispose();
      editorInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    const ed = editorInstanceRef.current;
    const monaco = monacoModuleRef.current;
    if (!ed || !monaco || !state.file) return;
    const model = ed.getModel();
    if (model) {
      model.setValue(state.file.content);
      monaco.editor.setModelLanguage(model, state.file.lang);
    }
    requestAnimationFrame(() => ed.layout());
  }, [state.file]);

  const fileName = state.file?.path.split("/").pop();

  return (
    <div className="agent-ide">
      {/* Tab bar */}
      <div className="agent-tabs">
        {state.recentFiles.slice(-6).map((f, i) => {
          const name = f.split("/").pop();
          const active = activeTab === "code" && f === state.file?.path;
          return (
            <div
              key={i}
              className={`agent-tab ${active ? "active" : ""}`}
              title={f}
              onClick={() => setActiveTab("code")}
            >
              {name}
            </div>
          );
        })}
        {!state.file && !state.screenshot && <div className="agent-tab active">waiting...</div>}
        {state.screenshot && (
          <div
            className={`agent-tab ${activeTab === "browser" ? "active" : ""}`}
            onClick={() => setActiveTab("browser")}
          >
            Browser
          </div>
        )}
        <div className="agent-badge-wrap">
          <span className="agent-badge">pair</span>
        </div>
      </div>

      {/* Editor (hidden when browser tab active) */}
      <div className="agent-editor-wrap" style={{ display: activeTab === "code" ? undefined : "none" }}>
        <div ref={editorContainerRef} className="agent-editor-inner" />
      </div>

      {/* Browser preview */}
      {activeTab === "browser" && state.screenshot && (
        <div className="agent-browser">
          {state.url && <div className="agent-url-bar">{state.url}</div>}
          <img src={`data:image/png;base64,${state.screenshot}`} alt="Browser screenshot" />
        </div>
      )}

      {/* Shell */}
      <div className={`agent-shell ${shellOpen ? "open" : ""}`}>
        <div className="agent-shell-header" onClick={() => setShellOpen(o => !o)}>
          <span>{state.command ? `$ ${state.command.cmd}` : "Terminal"}</span>
          <span style={{ opacity: 0.4 }}>{shellOpen ? "\u25BE" : "\u25B8"}</span>
        </div>
        {shellOpen && (
          <pre className="agent-shell-output">
            {state.command?.output ?? ""}
          </pre>
        )}
      </div>
    </div>
  );
}
