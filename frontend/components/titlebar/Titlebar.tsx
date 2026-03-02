interface Props {
  logoSrc: string;
  termOpen: boolean;
  explorerOpen: boolean;
  tensorOpen: boolean;
  twinMode: boolean;
  showTwin: boolean;
  onToggleTerm: () => void;
  onToggleExplorer: () => void;
  onToggleTensor: () => void;
  onToggleTwin: () => void;
}

export function Titlebar({
  logoSrc, termOpen, explorerOpen, tensorOpen, twinMode, showTwin,
  onToggleTerm, onToggleExplorer, onToggleTensor, onToggleTwin,
}: Props) {
  return (
    <div className="titlebar">
      <div className="titlebar-brand">
        <img src={logoSrc} alt="" className="titlebar-icon" />
      </div>
      <div style={{ flex: 1 }} />
      {!twinMode && (
        <>
          <button className={`titlebar-btn ${explorerOpen ? "active" : ""}`} onClick={onToggleExplorer}>Files</button>
          <button className={`titlebar-btn ${termOpen ? "active" : ""}`} onClick={onToggleTerm}>Terminal</button>
          <button className={`titlebar-btn ${tensorOpen ? "active" : ""}`} onClick={onToggleTensor}>Tensor</button>
        </>
      )}
      {showTwin && (
        <button className={`titlebar-btn ${twinMode ? "active" : ""}`} onClick={onToggleTwin}>Twin</button>
      )}
    </div>
  );
}
