import { useState } from "react";
import { api } from "../../api";

interface Props {
  logoSrc: string;
  onLogin: () => void;
  overlay?: boolean;
}

export function LoginScreen({ logoSrc, onLogin, overlay }: Props) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password.trim() || loading) return;
    setLoading(true);
    setError(false);
    const result = await api.login(password);
    setLoading(false);
    if (result) {
      onLogin();
    } else {
      setError(true);
      setPassword("");
    }
  }

  return (
    <div className={overlay ? "login-overlay" : "login-screen"}>
      <form className="login-box" onSubmit={handleSubmit}>
        <img src={logoSrc} alt="Tensor" className="login-logo" />
        <input
          type="password"
          className={`login-input ${error ? "error" : ""}`}
          placeholder="Password"
          value={password}
          onChange={(e) => { setPassword(e.target.value); setError(false); }}
          autoFocus
        />
        <button className="login-btn" type="submit" disabled={loading || !password.trim()}>
          {loading ? "..." : "Connect"}
        </button>
      </form>
    </div>
  );
}
