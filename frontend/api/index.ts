const BASE = "/api";

async function post<T>(path: string, body: object): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  return res.json() as Promise<T>;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

export const api = {
  listDir: (path: string) =>
    post<{ entries: FileEntry[]; error?: string }>("/list_dir", { path }),
  readFile: (path: string) =>
    post<{ content?: string; error?: string }>("/read_file", { path }),
  writeFile: (path: string, content: string) =>
    post<{ ok?: boolean; error?: string }>("/write_file", { path, content }),
  runShell: (command: string, cwd?: string) =>
    post<{ output: string; code: number }>("/run_shell", { command, cwd }),
  generate: (prompt: string, max_tokens = 2048, temperature = 0.0, use_cloud = true, model = "gpt-5.3-codex") =>
    post<{ result?: string; error?: string }>("/generate", {
      prompt, max_tokens, temperature, use_cloud, model,
    }),
  search: (query: string, max_results = 6) =>
    post<{ results?: string; error?: string }>("/search", { query, max_results }),
  fetchUrl: (url: string, max_chars = 8000) =>
    post<{ content?: string; error?: string }>("/fetch", { url, max_chars }),
  getModels: () => get<{ models: { id: string; provider: string }[] }>("/models"),
  listConversations: () => get<{ conversations: string[] }>("/conversations"),
  getConversation: (id: string) =>
    get<{ id: string; summary: string; turns: { role: string; text: string }[] }>(`/conversations/${encodeURIComponent(id)}`),
  deleteConversation: async (id: string) => {
    await fetch(`${BASE}/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
  getTopics: () =>
    get<{ topics: { topic: string; conversations: string[] }[]; titles: Record<string, string> }>("/conversations/topics/grouped"),
  setConversationTitle: (id: string, title: string) =>
    fetch(`/api/conversations/${encodeURIComponent(id)}/title`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  login: async (pin: string): Promise<boolean> => {
    const res = await fetch(`${BASE}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    return res.ok;
  },
  logout: () => post<{ ok: boolean }>("/logout", {}),
  authStatus: () => get<{ authed: boolean }>("/auth_status"),
};
