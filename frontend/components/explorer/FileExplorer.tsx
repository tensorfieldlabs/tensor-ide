import { useEffect, useState } from "react";
import {
  Folder,
  File,
  FileCode2,
  FileJson,
  FileText,
  TerminalSquare,
  Settings,
  RefreshCw,
  CornerLeftUp,
  Image as ImageIcon,
  Database,
  Upload,
} from "lucide-react";
import { api } from "../../api";
import type { FileEntry } from "../../api";

interface Props {
  cwd: string;
  activeFile: string | null;
  hidden?: boolean;
  onCwdChange?: (cwd: string) => void;
  onOpen?: (path: string, content: string) => void;
}

export function FileExplorer({
  cwd,
  activeFile,
  hidden,
  onCwdChange,
  onOpen,
}: Props) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [uploading, setUploading] = useState(false);

  async function loadDir(path: string) {
    const res = await api.listDir(path);
    if (res.entries) {
      // Sort: Directories first, then files, both alphabetically
      const sorted = res.entries.sort((a, b) => {
        if (a.is_dir === b.is_dir) return a.name.localeCompare(b.name);
        return a.is_dir ? -1 : 1;
      });
      setEntries(sorted);
    }
  }

  useEffect(() => {
    let active = true;
    api.listDir(cwd).then((res) => {
      if (active && res.entries) {
        const sorted = res.entries.sort((a, b) => {
          if (a.is_dir === b.is_dir) return a.name.localeCompare(b.name);
          return a.is_dir ? -1 : 1;
        });
        setEntries(sorted);
      }
    });
    return () => {
      active = false;
    };
  }, [cwd]);

  async function handleClick(entry: FileEntry) {
    if (entry.is_dir) {
      onCwdChange?.(entry.path);
    } else {
      const res = await api.readFile(entry.path);
      if (res.content !== undefined) onOpen?.(entry.path, res.content);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setUploading(true);
    const form = new FormData();
    form.append("dir", cwd);
    for (const f of Array.from(files)) form.append("files", f);
    try {
      await fetch("/api/upload", {
        method: "POST",
        body: form,
        headers: { Authorization: `Bearer ${localStorage.getItem("tensor_session") || ""}` },
      });
      await loadDir(cwd);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  function goUp() {
    // Basic path parsing to go up a directory
    const parts = cwd.replace(/\/$/, "").split("/");
    if (parts.length > 1) {
      parts.pop();
      const parent = parts.join("/") || "/";
      onCwdChange?.(parent);
    }
  }

  function renderIcon(entry: FileEntry) {
    const size = 14;

    if (entry.is_dir) {
      return (
        <Folder
          size={size}
          color="rgba(120, 170, 255, 0.9)"
          fill="rgba(120, 170, 255, 0.2)"
          strokeWidth={2}
        />
      );
    }

    const ext = entry.name.split(".").pop()?.toLowerCase() ?? "";

    switch (ext) {
      case "ts":
      case "tsx":
        return <FileCode2 size={size} color="#60a5fa" strokeWidth={2} />;
      case "js":
      case "jsx":
        return <FileCode2 size={size} color="#fcd34d" strokeWidth={2} />;
      case "py":
        return <FileCode2 size={size} color="#34d399" strokeWidth={2} />;
      case "rs":
      case "go":
      case "cpp":
      case "c":
      case "java":
        return <FileCode2 size={size} color="#fb923c" strokeWidth={2} />;
      case "json":
        return <FileJson size={size} color="#a78bfa" strokeWidth={2} />;
      case "md":
      case "txt":
        return <FileText size={size} color="#9ca3af" strokeWidth={2} />;
      case "css":
      case "scss":
      case "html":
        return <FileCode2 size={size} color="#f472b6" strokeWidth={2} />;
      case "sh":
      case "bash":
      case "zsh":
        return <TerminalSquare size={size} color="#4ade80" strokeWidth={2} />;
      case "toml":
      case "yaml":
      case "yml":
      case "ini":
      case "conf":
        return <Settings size={size} color="#9ca3af" strokeWidth={2} />;
      case "png":
      case "jpg":
      case "jpeg":
      case "svg":
      case "gif":
      case "webp":
        return <ImageIcon size={size} color="#a78bfa" strokeWidth={2} />;
      case "sql":
      case "db":
      case "sqlite":
        return <Database size={size} color="#60a5fa" strokeWidth={2} />;
      default:
        return (
          <File size={size} color="rgba(255,255,255,0.4)" strokeWidth={2} />
        );
    }
  }

  return (
    <div className={`explorer${hidden ? " hidden" : ""}`}>
      <div className="explorer-header">
        <span>Files</span>
        <div style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={goUp}
            title="Go up a directory"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <CornerLeftUp size={14} strokeWidth={2.5} />
          </button>
          <button
            onClick={() => loadDir(cwd)}
            title="Refresh"
            style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
          >
            <RefreshCw size={13} strokeWidth={2.5} />
          </button>
          <label
            title="Upload files"
            style={{ display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", opacity: uploading ? 0.4 : 1 }}
          >
            <Upload size={13} strokeWidth={2.5} />
            <input type="file" multiple onChange={handleUpload} style={{ display: "none" }} disabled={uploading} />
          </label>
        </div>
      </div>
      <div className="explorer-list">
        {entries.map((entry) => (
          <div
            key={entry.path}
            className={`explorer-item ${entry.is_dir ? "dir" : ""} ${activeFile === entry.path ? "active" : ""}`}
            onClick={() => handleClick(entry)}
            title={entry.path}
          >
            <span
              className="explorer-icon"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              {renderIcon(entry)}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
              {entry.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
