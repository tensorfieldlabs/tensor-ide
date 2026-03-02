import { useState, useEffect } from "react";
import { Titlebar } from "./components/titlebar/Titlebar";
import { TensorPanel } from "./components/tensor/TensorPanel";
import { IdePane } from "./components/pane/IdePane";
import { LoginScreen } from "./components/login/LoginScreen";
import { api } from "./api";
import { useLiveLogoSrc } from "./logo";
import "./styles/App.css";

export type OpenFile = { path: string; content: string; lang: string };

export function langFromPath(path: string): string {
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
  const [twinMode, setTwinMode] = useState(false);
  const [twinExiting, setTwinExiting] = useState(false);
  const [agentFile, setAgentFile] = useState<OpenFile | null>(null);
  const [agentCommand, setAgentCommand] = useState<{ cmd: string; output: string } | null>(null);
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
        twinMode={twinMode}
        onToggleTwin={() => {
          if (twinMode) {
            setTwinExiting(true);
            setTimeout(() => { setTwinMode(false); setTwinExiting(false); }, 550);
          } else {
            setTwinMode(true);
          }
        }}
      />
      <div className={twinMode || twinExiting ? "ide-twin-split" : "ide-twin-wrap"}>
        {(twinMode || twinExiting) && (
          <>
            <div className={`ide-twin-left ${twinExiting ? "exiting" : ""}`}>
              <IdePane
                initialCwd="/"
                hideTensor
                variant="agent"
                agentFile={agentFile}
                agentCommand={agentCommand}
              />
            </div>
            <div className={`ide-twin-divider ${twinExiting ? "exiting" : ""}`} />
          </>
        )}
        <IdePane
          initialCwd="/"
          onAgentFile={(path, content) => setAgentFile({ path, content, lang: langFromPath(path) })}
          onAgentCommand={(cmd, output) => setAgentCommand({ cmd, output })}
        />
      </div>
    </div>
  );
}
