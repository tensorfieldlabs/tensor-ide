import { useEffect, useRef } from "react";
import { api } from "../../api";
import type { OpenFile } from "../../App";

interface Props {
  file: OpenFile | null;
  onSave?: (path: string, content: string) => void;
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
          api.writeFile(f.path, val);
          onSaveRef.current?.(f.path, val);
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
      editorRef.current?.dispose();
    };
  }, []);

  // Update content/language when file changes
  useEffect(() => {
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco || !file) return;

    const model = editor.getModel();
    if (model) {
      monaco.editor.setModelLanguage(model, file.lang);
      if (editor.getValue() !== file.content) {
        editor.setValue(file.content);
      }
    }
  }, [file]);

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
