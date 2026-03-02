import { useState, useEffect } from "react";
import { FileExplorer } from "./components/explorer/FileExplorer";
import { CodeEditor } from "./components/editor/CodeEditor";
import { Terminal } from "./components/terminal/Terminal";
import { Titlebar } from "./components/titlebar/Titlebar";
import { TensorPanel } from "./components/tensor/TensorPanel";
import { IdePane } from "./components/pane/IdePane";
import { LoginScreen } from "./components/login/LoginScreen";
import { api } from "./api";
import { useLiveLogoSrc } from "./logo";
import "./styles/App.css";

export type OpenFile = { path: string; content: string; lang: string };

function langFromPath(path: string): string {
  const ext = path.split(".").pop() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
    py: "python", rs: "rust", go: "go", json: "json", md: "markdown",
    css: "css", html: "html", sh: "shell", toml: "toml", yaml: "yaml",
  };
  return map[ext] ?? "plaintext";
}

function detectPhone(): boolean {
  const ua = navigator.userAgent || "";
  if (/iPhone|iPod/.test(ua)) return true;
  if (/Android/.test(ua) && /Mobile/.test(ua)) return true;
  if (/Windows Phone|webOS|BlackBerry/i.test(ua)) return true;
  const short = Math.min(screen.width, screen.height);
  if ("ontouchstart" in window && short <= 430) return true;
  return false;
}

const IS_PHONE = detectPhone();

export default function App() {
  const [authed, setAuthed] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  const [cwd, setCwd] = useState("/");
  const logoSrc = useLiveLogoSrc();

  useEffect(() => {
    api.authStatus().then(r => {
      setAuthed(r.authed);
      setAuthChecked(true);
    }).catch(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    const handler = () => setSessionExpired(true);
    window.addEventListener("tensor:session-expired", handler);
    return () => window.removeEventListener("tensor:session-expired", handler);
  }, []);
  const [termOpen, setTermOpen] = useState(!IS_PHONE && window.innerHeight >= 600);
  const [explorerOpen, setExplorerOpen] = useState(!IS_PHONE && window.innerWidth >= 800);
  const [tensorOpen, setTensorOpen] = useState(IS_PHONE || window.innerWidth >= 1100);
  const [pairMode, setPairMode] = useState(false);
  const [pairExiting, setPairExiting] = useState(false);
  const [agentFile, setAgentFile] = useState<OpenFile | null>(null);
  const [agentCommand, setAgentCommand] = useState<{ cmd: string; output: string } | null>(null);

  useEffect(() => {
    if (IS_PHONE) return;
    let lastWidth = window.innerWidth;
    let lastHeight = window.innerHeight;
    const handleResize = () => {
      const width = window.innerWidth;
      const height = window.innerHeight;
      if (lastWidth >= 1100 && width < 1100) { setTensorOpen(false); setPairMode(false); }
      if (lastWidth >= 800 && width < 800) setExplorerOpen(false);
      if (lastHeight >= 600 && height < 600) setTermOpen(false);
      if (lastWidth < 1100 && width >= 1100) setTensorOpen(true);
      if (lastWidth < 800 && width >= 800) setExplorerOpen(true);
      if (lastHeight < 600 && height >= 600) setTermOpen(true);
      lastWidth = width; lastHeight = height;
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    if (IS_PHONE) return;
    const handleDragOver = (e: DragEvent) => e.preventDefault();
    const handleDrop = async (e: DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer?.files[0];
      if (file) {
        const text = await file.text();
        setOpenFile({ path: file.name, content: text, lang: langFromPath(file.name) });
      }
    };
    window.addEventListener("dragover", handleDragOver);
    window.addEventListener("drop", handleDrop);
    return () => {
      window.removeEventListener("dragover", handleDragOver);
      window.removeEventListener("drop", handleDrop);
    };
  }, []);

  function handleOpen(filePath: string, content: string) {
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

  if (!authChecked) return null;
  if (!authed) return <LoginScreen logoSrc={logoSrc} onLogin={() => setAuthed(true)} />;

  if (IS_PHONE) {
    return (
      <div className="ide phone">
        <TensorPanel openFile={null} hidden={false} />
      </div>
    );
  }

  return (
    <div className="ide">
      {sessionExpired && <LoginScreen logoSrc={logoSrc} onLogin={() => { setAuthed(true); setSessionExpired(false); }} overlay />}
      <Titlebar
        logoSrc={logoSrc}
        termOpen={termOpen}
        explorerOpen={explorerOpen}
        tensorOpen={tensorOpen}
        pairMode={pairMode}
        showPair={pairMode || (explorerOpen && tensorOpen)}
        onToggleTerm={() => setTermOpen(o => !o)}
        onToggleExplorer={() => setExplorerOpen(o => {
          const next = !o;
          if (next && window.innerWidth < 1100) setTensorOpen(false);
          return next;
        })}
        onToggleTensor={() => setTensorOpen(o => {
          const next = !o;
          if (next && window.innerWidth < 1100) setExplorerOpen(false);
          return next;
        })}
        onTogglePair={() => {
          if (pairMode) {
            setPairExiting(true);
            setTimeout(() => { setPairMode(false); setPairExiting(false); }, 550);
          } else {
            setPairMode(true);
          }
        }}
      />
      {pairMode ? (
        <div className="ide-pair-split">
          <div className={`ide-pair-left ${pairExiting ? "exiting" : ""}`}>
            <IdePane
              initialCwd="/"
              hideTensor
              variant="agent"
              agentFile={agentFile}
              agentCommand={agentCommand}
            />
          </div>
          <div className={`ide-pair-divider ${pairExiting ? "exiting" : ""}`} />
          <div className={`ide-pair-right ${pairExiting ? "exiting" : ""}`}>
            <IdePane
              initialCwd="/"
              onAgentFile={(path, content) => setAgentFile({ path, content, lang: langFromPath(path) })}
              onAgentCommand={(cmd, output) => setAgentCommand({ cmd, output })}
            />
          </div>
        </div>
      ) : (
        <div className="ide-body">
          <FileExplorer
            cwd={cwd}
            onCwdChange={setCwd}
            onOpen={handleOpen}
            activeFile={openFile?.path ?? null}
            hidden={!explorerOpen}
          />
          <div className="ide-center">
            <div className="ide-editor">
              <CodeEditor
                file={openFile}
                onSave={handleSave}
                onOpenExplorer={() => setExplorerOpen(o => {
                  const next = !o;
                  if (next && window.innerWidth < 1100) setTensorOpen(false);
                  return next;
                })}
              />
            </div>
            <Terminal cwd={cwd} hidden={!termOpen} onClose={() => setTermOpen(false)} />
          </div>
          <TensorPanel
            openFile={openFile}
            cwd={cwd}
            hidden={!tensorOpen}
            onClose={() => setTensorOpen(false)}
            onFileChanged={handleFileChanged}
          />
        </div>
      )}
    </div>
  );
}
