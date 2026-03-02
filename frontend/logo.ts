import { useEffect, useState } from "react";

function urlFor(version: string): string {
  return `/hogue.svg?v=${encodeURIComponent(version || "0")}`;
}

export function useLiveLogoSrc(pollMs = 4000): string {
  const [version, setVersion] = useState<string>(() => String(Date.now()));

  useEffect(() => {
    let alive = true;
    let timer: number | null = null;

    const tick = async () => {
      try {
        const res = await fetch("/api/logo_version", { cache: "no-store" });
        if (res.ok) {
          const data = (await res.json()) as { version?: string };
          const next = String(data.version || "");
          if (alive && next) {
            setVersion((prev) => (prev === next ? prev : next));
          }
        }
      } catch {
        // Keep current logo if probe fails.
      } finally {
        if (alive) timer = window.setTimeout(tick, pollMs);
      }
    };

    tick();
    return () => {
      alive = false;
      if (timer != null) window.clearTimeout(timer);
    };
  }, [pollMs]);

  useEffect(() => {
    const favicon = document.getElementById("app-favicon") as HTMLLinkElement | null;
    if (favicon) favicon.href = urlFor(version);
  }, [version]);

  return urlFor(version);
}
