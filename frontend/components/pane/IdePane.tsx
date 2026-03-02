import { useState, useEffect, useRef } from "react";
import { FileExplorer } from "../explorer/FileExplorer";
import { CodeEditor } from "../editor/CodeEditor";
import { DiffEditor } from "../editor/DiffEditor";
import { Terminal } from "../terminal/Terminal";
import { TensorPanel } from "../tensor/TensorPanel";
import { BrowserPanel } from "../browser/BrowserPanel";
import { api } from "../../api";
import type { OpenFile } from "../../App";

function langFromPath(path: string): string {
  const ext = path.split(".").pop() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", json: "json", md: "markdown",
    css: "css", html: "html", sh: "shell", toml: "toml", yaml: "yaml",
  };
  return map[ext] ?? "plaintext";
}

interface Props {
  initialCwd?: string;
  hideTensor?: boolean;
  variant?: "default" | "agent";
  onAgentScreenshot?: (base64: string) => void;
  onAgentUrl?: (url: string) => void;
  onAgentFile?: (path: string, content: string) => void;
  onAgentCommand?: (cmd: string, output: string) => void;
  agentFile?: OpenFile | null;
  agentCwd?: string;
  agentCommand?: { cmd: string; output: string } | null;
}

export function IdePane({
  initialCwd = "/Users/reeshogue", hideTensor,
  variant = "default",
  onAgentScreenshot, onAgentUrl, onAgentFile, onAgentCommand,
  agentFile, agentCwd, agentCommand,
}: Props) {
  const isAgent = variant === "agent";

  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  const [cwd, setCwd] = useState(initialCwd);
  const [explorerOpen, setExplorerOpen] = useState(true);
  const [termOpen, setTermOpen] = useState(true);
  const [tensorOpen, setTensorOpen] = useState(false);

  // Diff tour state
  const [diffState, setDiffState] = useState<{ original: string; modified: string; lang: string } | null>(null);
  const prevFileRef = useRef<OpenFile | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Terminal inject — latest AI command
  const [termInject, setTermInject] = useState<string | null>(null);

  // Block clicks + keyboard input but allow scroll in agent pane
  useEffect(() => {
    if (!isAgent) return;
    const el = bodyRef.current;
    if (!el) return;
    const blockMouse = (e: MouseEvent) => e.preventDefault();
    const blockKey = (e: KeyboardEvent) => e.stopImmediatePropagation();
    el.addEventListener("mousedown", blockMouse, { capture: true });
    el.addEventListener("click", blockMouse, { capture: true });
    el.addEventListener("keydown", blockKey, { capture: true });
    el.addEventListener("keypress", blockKey, { capture: true });
    return () => {
      el.removeEventListener("mousedown", blockMouse, { capture: true });
      el.removeEventListener("click", blockMouse, { capture: true });
      el.removeEventListener("keydown", blockKey, { capture: true });
      el.removeEventListener("keypress", blockKey, { capture: true });
    };
  }, [isAgent]);

  useEffect(() => {
    if (!isAgent || !agentFile) return;
    const prev = prevFileRef.current;
    // If same file with different content — show diff tour
    if (prev && prev.path === agentFile.path && prev.content !== agentFile.content) {
      setDiffState({ original: prev.content, modified: agentFile.content, lang: agentFile.lang });
    } else {
      setDiffState(null);
    }
    prevFileRef.current = agentFile;
    setOpenFile(agentFile);
    setExplorerOpen(true);
  }, [isAgent, agentFile]);

  useEffect(() => {
    if (isAgent && agentCwd) setCwd(agentCwd);
  }, [isAgent, agentCwd]);

  // Inject AI commands into agent terminal
  useEffect(() => {
    if (isAgent && agentCommand) setTermInject(agentCommand.cmd);
  }, [isAgent, agentCommand]);

  function handleOpen(filePath: string, content: string) {
    if (isAgent) return;
    setOpenFile(prev => prev?.path === filePath ? null : { path: filePath, content, lang: langFromPath(filePath) });
  }

  function handleSave(_path: string, content: string) {
    setOpenFile(prev => prev ? { ...prev, content } : null);
  }

  async function handleFileChanged(path: string) {
    setOpenFile(prev => {
      if (!prev || prev.path !== path) return prev;
      api.readFile(path).then(res => {
        if (res.content !== undefined)
          setOpenFile(p => p?.path === path ? { ...p, content: res.content! } : p);
      });
      return prev;
    });
  }

  return (
    <div className={`ide-pane ${isAgent ? "ide-pane-agent" : ""}`}>
      <div className="ide-pane-toolbar">
        {isAgent ? (
          <span className="ide-pane-agent-badge">AI</span>
        ) : (
          <>
            <button
              className={`ide-pane-btn ${explorerOpen ? "active" : ""}`}
              onClick={() => setExplorerOpen(o => { const next = !o; if (next) setTensorOpen(false); return next; })}
            >Files</button>
            <button
              className={`ide-pane-btn ${termOpen ? "active" : ""}`}
              onClick={() => setTermOpen(o => !o)}
            >Terminal</button>
            {!hideTensor && (
              <button
                className={`ide-pane-btn ${tensorOpen ? "active" : ""}`}
                onClick={() => setTensorOpen(o => { const next = !o; if (next) setExplorerOpen(false); return next; })}
              >Tensor</button>
            )}
          </>
        )}
      </div>
      <div className="ide-pane-body" ref={bodyRef}>
        <FileExplorer
          cwd={cwd}
          onCwdChange={isAgent ? undefined : setCwd}
          onOpen={handleOpen}
          activeFile={openFile?.path ?? null}
          hidden={!explorerOpen}
        />
        <div className="ide-center">
          <div className="ide-editor">
            {isAgent && diffState ? (
              <DiffEditor
                original={diffState.original}
                modified={diffState.modified}
                lang={diffState.lang}
                onDone={() => setDiffState(null)}
              />
            ) : (
              <CodeEditor
                file={openFile}
                onSave={isAgent ? undefined : handleSave}
                onOpenExplorer={isAgent ? undefined : () => setExplorerOpen(o => !o)}
              />
            )}
          </div>
          <Terminal
            cwd={cwd}
            hidden={!termOpen}
            onClose={isAgent ? undefined : () => setTermOpen(false)}
            inject={isAgent ? termInject : undefined}
          />
        </div>
        {!hideTensor && !isAgent && (
          <TensorPanel
            openFile={openFile}
            cwd={cwd}
            hidden={!tensorOpen}
            onClose={() => setTensorOpen(false)}
            onFileChanged={handleFileChanged}
            onAgentFile={onAgentFile}
            onAgentCommand={onAgentCommand}
            onAgentScreenshot={onAgentScreenshot}
            onAgentUrl={onAgentUrl}
          />
        )}
        {isAgent && <BrowserPanel />}
      </div>
    </div>
  );
}
