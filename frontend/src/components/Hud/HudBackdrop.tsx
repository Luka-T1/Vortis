const VANISH_X = 50;
const VANISH_Y = 38;
const FAN = [-40, -10, 14, 30, 42, 50, 58, 70, 86, 110, 140];
const HORIZON = [46, 58, 74, 96];

export function HudBackdrop() {
  return (
    <div className="vx-backdrop" aria-hidden="true">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        {FAN.map((x) => (
          <line key={`b${x}`} x1={VANISH_X} y1={VANISH_Y} x2={x} y2={100} />
        ))}
        {FAN.map((x) => (
          <line key={`t${x}`} x1={VANISH_X} y1={VANISH_Y} x2={x} y2={0} />
        ))}
        {HORIZON.map((y) => (
          <line key={`h${y}`} className="h" x1={0} y1={y} x2={100} y2={y} />
        ))}
        <line className="h" x1={0} y1={8} x2={100} y2={8} />
      </svg>
    </div>
  );
}
