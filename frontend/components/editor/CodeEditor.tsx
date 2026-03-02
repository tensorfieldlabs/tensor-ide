import { useCallback, useEffect, useRef } from "react";
import { api } from "../../api";
import type { OpenFile } from "../../App";
import type { IdentityEvent } from "../../api";

interface Props {
  file: OpenFile | null;
  onSave: (path: string, content: string) => void;
  onOpenExplorer?: () => void;
}

const TENSOR_THEME = {
  base: "vs-dark" as const,
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
    "editor.lineHighlightBackground": "#ffffff0a",
    "editor.selectionBackground": "#3b82f644",
    "editorGutter.background": "#00000000",
    "editorLineNumber.foreground": "#ffffff44",
    "editorLineNumber.activeForeground": "#ffffff99",
    "editorCursor.foreground": "#60a5fa",
    "editor.findMatchBackground": "#3b82f644",
  },
};

const EDITOR_OPTS: Record<string, unknown> = {
  fontSize: 13,
  fontFamily: "'JetBrains Mono', monospace",
  fontLigatures: true,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  wordWrap: "on",
  padding: { top: 12 },
  smoothScrolling: true,
  cursorBlinking: "smooth",
  cursorSmoothCaretAnimation: "on",
};

import type * as MonacoType from "monaco-editor";

export function CodeEditor({ file, onSave, onOpenExplorer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<MonacoType.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof MonacoType | null>(null);
  const fileRef = useRef(file);
  fileRef.current = file;
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const behaviorQueueRef = useRef<IdentityEvent[]>([]);
  const behaviorFlushTimerRef = useRef<number | null>(null);
  const editFlushTimerRef = useRef<number | null>(null);
  const suppressEditEventsRef = useRef(false);
  const pendingEditRef = useRef({
    changes: 0,
    charsAdded: 0,
    charsRemoved: 0,
    newlinesAdded: 0,
    newlinesRemoved: 0,
    firstTs: 0,
    lastTs: 0,
  });

  const flushBehavior = useCallback(async () => {
    if (!behaviorQueueRef.current.length) return;
    const batch = behaviorQueueRef.current.splice(0, 128);
    try {
      await api.logIdentity(batch);
    } catch {
      // Drop telemetry errors to avoid impacting the editor UX.
    }
  }, []);

  const queueBehavior = useCallback((event: IdentityEvent) => {
    behaviorQueueRef.current.push({
      ...event,
      client_ts: event.client_ts ?? Date.now() / 1000,
    });
    if (behaviorQueueRef.current.length >= 16) {
      void flushBehavior();
      return;
    }
    if (behaviorFlushTimerRef.current === null) {
      behaviorFlushTimerRef.current = window.setTimeout(() => {
        behaviorFlushTimerRef.current = null;
        void flushBehavior();
      }, 4000);
    }
  }, [flushBehavior]);

  const flushPendingEdits = useCallback(() => {
    const p = pendingEditRef.current;
    if (!p.changes) return;
    queueBehavior({
      source: "editor",
      action: "edit",
      metrics: {
        changes: p.changes,
        chars_added: p.charsAdded,
        chars_removed: p.charsRemoved,
        newlines_added: p.newlinesAdded,
        newlines_removed: p.newlinesRemoved,
        duration_ms: Math.max(0, Math.round((p.lastTs - p.firstTs) * 1000)),
      },
    });
    pendingEditRef.current = {
      changes: 0,
      charsAdded: 0,
      charsRemoved: 0,
      newlinesAdded: 0,
      newlinesRemoved: 0,
      firstTs: 0,
      lastTs: 0,
    };
  }, [queueBehavior]);

  // Load Monaco once
  useEffect(() => {
    let cancelled = false;

    async function init() {
      const monaco = await import("monaco-editor");
      if (cancelled) return;
      monacoRef.current = monaco;

      monaco.editor.defineTheme("tensor", TENSOR_THEME);

      if (containerRef.current) {
        const editor = monaco.editor.create(containerRef.current, {
          ...EDITOR_OPTS,
          theme: "tensor",
          language: fileRef.current?.lang ?? "plaintext",
          value: fileRef.current?.content ?? "",
        });

        editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
          const f = fileRef.current;
          if (!f) return;
          const val = editor.getValue();
          flushPendingEdits();
          queueBehavior({
            source: "editor",
            action: "save",
            metrics: {
              path_len: f.path.length,
              file_ext_len: (f.path.split(".").pop() || "").length,
              content_len: val.length,
              lang_len: f.lang.length,
            },
          });
          void flushBehavior();
          api.writeFile(f.path, val);
          onSaveRef.current(f.path, val);
        });

        editor.onDidChangeModelContent((evt) => {
          if (suppressEditEventsRef.current) return;
          const now = Date.now() / 1000;
          const pending = pendingEditRef.current;
          if (!pending.firstTs) pending.firstTs = now;
          pending.lastTs = now;
          pending.changes += evt.changes.length;
          for (const change of evt.changes) {
            pending.charsAdded += change.text.length;
            pending.charsRemoved += change.rangeLength;
            pending.newlinesAdded += (change.text.match(/\n/g) || []).length;
            pending.newlinesRemoved += Math.max(0, change.range.endLineNumber - change.range.startLineNumber);
          }
          if (editFlushTimerRef.current !== null) {
            window.clearTimeout(editFlushTimerRef.current);
          }
          editFlushTimerRef.current = window.setTimeout(() => {
            editFlushTimerRef.current = null;
            flushPendingEdits();
            void flushBehavior();
          }, 2000);
        });

        editorRef.current = editor;

        const ro = new ResizeObserver(() => editor.layout());
        ro.observe(containerRef.current);

        return () => {
          ro.disconnect();
        };
      }
    }

    init();
    return () => {
      cancelled = true;
      flushPendingEdits();
      void flushBehavior();
      if (behaviorFlushTimerRef.current !== null) {
        window.clearTimeout(behaviorFlushTimerRef.current);
        behaviorFlushTimerRef.current = null;
      }
      if (editFlushTimerRef.current !== null) {
        window.clearTimeout(editFlushTimerRef.current);
        editFlushTimerRef.current = null;
      }
      editorRef.current?.dispose();
    };
  }, [flushBehavior, flushPendingEdits, queueBehavior]);

  // Update content/language when file changes
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || !file) return;

    const model = editor.getModel();
    if (model) {
      monaco.editor.setModelLanguage(model, file.lang);
      if (editor.getValue() !== file.content) {
        suppressEditEventsRef.current = true;
        editor.setValue(file.content);
        suppressEditEventsRef.current = false;
      }
    }
    flushPendingEdits();
    queueBehavior({
      source: "editor",
      action: "open_file",
      metrics: {
        path_len: file.path.length,
        file_ext_len: (file.path.split(".").pop() || "").length,
        content_len: file.content.length,
        lang_len: file.lang.length,
      },
    });
    void flushBehavior();
  }, [file, flushBehavior, flushPendingEdits, queueBehavior]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        position: "relative",
      }}
    >
      {!file ? (
        <div className="editor-empty" onClick={onOpenExplorer}>
          <div className="editor-empty-icon">◈</div>
          <span>open a file to edit</span>
        </div>
      ) : (
        <div className="editor-tabs">
          <div className="editor-tab active">
            <span>{file.path.split("/").pop()}</span>
          </div>
        </div>
      )}
      <div style={{ flex: 1, position: "relative", overflow: "hidden", display: file ? "block" : "none" }}>
        <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      </div>
    </div>
  );
}
