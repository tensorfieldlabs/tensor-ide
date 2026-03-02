interface Props {
  logoSrc: string;
  twinMode: boolean;
  onToggleTwin: () => void;
}

export function Titlebar({ logoSrc, twinMode, onToggleTwin }: Props) {
  return (
    <div className="titlebar">
      <div className="titlebar-brand">
        <img src={logoSrc} alt="" className="titlebar-icon" />
      </div>
      <div style={{ flex: 1 }} />
      <button className={`titlebar-btn ${twinMode ? "active" : ""}`} onClick={onToggleTwin}>Twin</button>
    </div>
  );
}
