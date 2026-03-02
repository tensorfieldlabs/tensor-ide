import { useEffect, useRef } from "react";
import type * as MonacoType from "monaco-editor";

interface Props {
  original: string;
  modified: string;
  lang: string;
  onDone: () => void;
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
    "diffEditor.insertedTextBackground": "#22c55e22",
    "diffEditor.removedTextBackground": "#ef444422",
    "diffEditor.insertedLineBackground": "#22c55e11",
    "diffEditor.removedLineBackground": "#ef444411",
    "editorGutter.background": "#00000000",
    "editorLineNumber.foreground": "#ffffff44",
    "editorLineNumber.activeForeground": "#ffffff99",
  },
};

// How long to linger on each hunk before moving to the next
const HUNK_DWELL_MS = 1200;
// Pause before starting the tour
const TOUR_START_DELAY_MS = 400;
// After last hunk, wait this long then call onDone
const DONE_DELAY_MS = 1800;

export function DiffEditor({ original, modified, lang, onDone }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<MonacoType.editor.IStandaloneDiffEditor | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];

    async function init() {
      const monaco = await import("monaco-editor");
      if (cancelled || !containerRef.current) return;

      monaco.editor.defineTheme("tensor", TENSOR_THEME);

      const diffEditor = monaco.editor.createDiffEditor(containerRef.current, {
        theme: "tensor",
        fontSize: 13,
        fontFamily: "'JetBrains Mono', monospace",
        fontLigatures: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        renderSideBySide: false, // inline diff
        readOnly: true,
        smoothScrolling: true,
        padding: { top: 12 },
        renderOverviewRuler: false,
        hideUnchangedRegions: { enabled: true, minimumLineCount: 3 },
      });

      editorRef.current = diffEditor;

      const originalModel = monaco.editor.createModel(original, lang);
      const modifiedModel = monaco.editor.createModel(modified, lang);
      diffEditor.setModel({ original: originalModel, modified: modifiedModel });

      // Wait for diff computation then tour through hunks
      const disposable = diffEditor.onDidUpdateDiff(() => {
        disposable.dispose();
        if (cancelled) return;

        const changes = diffEditor.getDiffComputationResult()?.changes ?? [];
        if (changes.length === 0) {
          timers.push(setTimeout(() => onDoneRef.current(), DONE_DELAY_MS));
          return;
        }

        const modEditor = diffEditor.getModifiedEditor();

        let i = 0;
        function visitNext() {
          if (cancelled) return;
          if (i >= changes.length) {
            timers.push(setTimeout(() => onDoneRef.current(), DONE_DELAY_MS));
            return;
          }
          const change = changes[i++];
          const line = change.modifiedStartLineNumber || change.modifiedEndLineNumber || 1;
          modEditor.revealLineInCenter(line, 0 /* Immediate */);
          timers.push(setTimeout(visitNext, HUNK_DWELL_MS));
        }

        timers.push(setTimeout(visitNext, TOUR_START_DELAY_MS));
      });
    }

    init();

    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
      editorRef.current?.dispose();
      editorRef.current = null;
    };
  }, [original, modified, lang]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%" }} />;
}
