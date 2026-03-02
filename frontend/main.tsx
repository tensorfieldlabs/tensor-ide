import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Dismiss splash screen
requestAnimationFrame(() => {
  const splash = document.getElementById("tensor-splash");
  if (splash) {
    splash.classList.add("fade");
    setTimeout(() => splash.remove(), 600);
  }
});
