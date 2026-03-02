import { useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

interface Props {
  cwd?: string;
  hidden?: boolean;
  onClose?: () => void;
  /** Agent mode: write text directly into terminal display (not via pty) */
  inject?: string | null;
}

export function Terminal({ hidden, onClose, inject }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(false);
  const [reconnecting, setReconnecting] = useState(false);

  useEffect(() => {
    if (mountedRef.current) return;
    mountedRef.current = true;

    const term = new XTerm({
      theme: {
        background: "#00000000",
        foreground: "rgba(255,245,235,0.85)",
        cursor: "#a0b4ff",
        cursorAccent: "#0a0808",
        black: "#ffffff1a",
        green: "#34d399",
        brightGreen: "#6ee7b7",
        red: "#fb7185",
        yellow: "#f59e0b",
        blue: "#60a5fa",
        magenta: "#a78bfa",
        cyan: "#22d3ee",
        white: "rgba(255,245,235,0.85)",
        brightWhite: "#ffffff",
      },
      fontFamily: "'SF Mono', 'JetBrains Mono', ui-monospace, monospace",
      fontSize: 13,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      allowTransparency: true,
    });

    const fit = new FitAddon();
    term.loadAddon(fit);

    xtermRef.current = term;
    fitRef.current = fit;

    if (containerRef.current) {
      term.open(containerRef.current);
      fit.fit();
    }

    let currentWs: WebSocket | null = null;
    let delay = 1000;
    let destroyed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    term.onData((data) => {
      if (currentWs?.readyState === WebSocket.OPEN)
        currentWs.send(JSON.stringify({ type: "input", data }));
    });

    term.onResize(({ cols, rows }) => {
      if (currentWs?.readyState === WebSocket.OPEN)
        currentWs.send(JSON.stringify({ type: "resize", cols, rows }));
    });

    function connect() {
      if (destroyed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const session = localStorage.getItem("tensor_session") || "";
      const ws = new WebSocket(`${proto}://${location.host}/ws/terminal?session=${session}`);
      currentWs = ws;
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        delay = 1000;
        setReconnecting(false);
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      };

      ws.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
        else term.write(e.data);
      };

      ws.onclose = () => {
        if (destroyed) return;
        setReconnecting(true);
        reconnectTimer = setTimeout(() => {
          delay = Math.min(delay * 2, 30000);
          connect();
        }, delay);
      };
    }

    connect();

    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {
        /* ignore */
      }
    });
    if (containerRef.current) ro.observe(containerRef.current);

    return () => {
      destroyed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      currentWs?.close();
      ro.disconnect();
      term.dispose();
      mountedRef.current = false;
    };
  }, []);

  // Agent inject: write AI commands directly into the terminal display
  useEffect(() => {
    if (!inject || !xtermRef.current) return;
    xtermRef.current.write("\r\n\x1b[36m$ " + inject + "\x1b[0m\r\n");
  }, [inject]);

  // Re-fit when panel becomes visible
  useEffect(() => {
    if (!hidden && fitRef.current) {
      setTimeout(() => {
        try {
          fitRef.current!.fit();
        } catch {
          /* ignore */
        }
      }, 50);
    }
  }, [hidden]);

  return (
    <div className={`terminal-pane${hidden ? " collapsed" : ""}`}>
      <div className="terminal-header" onClick={hidden ? onClose : undefined} style={hidden ? { cursor: "pointer" } : undefined}>
        <span>Terminal{reconnecting && <span className="terminal-reconnecting"> ⟳</span>}</span>
        <button className="terminal-toggle" onClick={onClose} title={hidden ? "Expand terminal" : "Collapse terminal"}>
          {hidden ? "\u25B2" : "\u25BC"}
        </button>
      </div>
      <div className="terminal-body">
        <div ref={containerRef} className="terminal-xterm-container" style={{ position: "absolute", inset: 0 }} />
      </div>
    </div>
  );
}
