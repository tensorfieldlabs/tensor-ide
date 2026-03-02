import { useEffect, useRef, useState } from "react";


interface Props {
  onClose?: () => void;
}

export function BrowserPanel({ onClose }: Props) {
  const imgRef = useRef<HTMLImageElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "disconnected">("connecting");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let destroyed = false;

    function connect() {
      if (destroyed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/browser`);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => setStatus("live");

      ws.onmessage = (e) => {
        if (typeof e.data === "string" && e.data.startsWith("CMD:")) {
          const cmd = e.data.slice(4);
          if (cmd === "OPEN") setOpen(true);
          else if (cmd === "CLOSE") setOpen(false);
          return;
        }
        // JPEG frame — direct DOM mutation for 24fps performance
        if (imgRef.current) {
          imgRef.current.src = `data:image/jpeg;base64,${e.data}`;
        }
      };

      ws.onclose = () => {
        if (destroyed) return;
        setStatus("disconnected");
        setTimeout(connect, 2000);
      };

      ws.onerror = () => ws.close();
    }

    connect();

    return () => {
      destroyed = true;
      ws?.close();
      wsRef.current = null;
    };
  }, []);

  return (
    <div className={`browser-panel${open ? "" : " browser-hidden"}`}>
      <div className="browser-header">
        <span className="browser-title">
          Browser
          {status === "live" && <span className="browser-live-dot" />}
          {status === "connecting" && <span className="browser-status"> connecting...</span>}
          {status === "disconnected" && <span className="browser-status"> reconnecting...</span>}
        </span>
        <button className="browser-close" onClick={() => { setOpen(false); onClose?.(); }} title="Close browser">✕</button>
      </div>
      <div className="browser-body">
        <img
          ref={imgRef}
          alt="Browser"
          style={{ display: status === "live" ? undefined : "none" }}
        />
        {status !== "live" && (
          <div className="browser-empty">
            {status === "connecting" ? "Starting browser..." : "Reconnecting..."}
          </div>
        )}
      </div>
    </div>
  );
}
