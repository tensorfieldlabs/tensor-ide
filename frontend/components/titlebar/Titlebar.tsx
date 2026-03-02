interface Props {
  logoSrc: string;
  termOpen: boolean;
  explorerOpen: boolean;
  tensorOpen: boolean;
  pairMode: boolean;
  showPair: boolean;
  onToggleTerm: () => void;
  onToggleExplorer: () => void;
  onToggleTensor: () => void;
  onTogglePair: () => void;
}

export function Titlebar({
  logoSrc, termOpen, explorerOpen, tensorOpen, pairMode, showPair,
  onToggleTerm, onToggleExplorer, onToggleTensor, onTogglePair,
}: Props) {
  return (
    <div className="titlebar">
      <div className="titlebar-brand">
        <img src={logoSrc} alt="" className="titlebar-icon" />
      </div>
      <div style={{ flex: 1 }} />
      {!pairMode && (
        <>
          <button className={`titlebar-btn ${explorerOpen ? "active" : ""}`} onClick={onToggleExplorer}>Files</button>
          <button className={`titlebar-btn ${termOpen ? "active" : ""}`} onClick={onToggleTerm}>Terminal</button>
          <button className={`titlebar-btn ${tensorOpen ? "active" : ""}`} onClick={onToggleTensor}>Tensor</button>
        </>
      )}
      {showPair && (
        <button className={`titlebar-btn ${pairMode ? "active" : ""}`} onClick={onTogglePair}>Twin</button>
      )}
    </div>
  );
}
