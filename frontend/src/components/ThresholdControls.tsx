interface Props {
  radius: number
  pad: number
  confidenceThreshold: number
  onRadius: (v: number) => void
  onPad: (v: number) => void
  onConfidenceThreshold: (v: number) => void
}

export function ThresholdControls(props: Props) {
  return (
    <section className="controls" aria-label="Matching thresholds">
      <label className="slider">
        <span className="slider-label">
          Distance radius <output>{props.radius} mi</output>
        </span>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={props.radius}
          aria-label="Distance radius (miles)"
          onChange={(e) => props.onRadius(Number(e.target.value))}
        />
      </label>
      <label className="slider">
        <span className="slider-label">
          Date padding <output>±{props.pad} days</output>
        </span>
        <input
          type="range"
          min={0}
          max={365}
          step={5}
          value={props.pad}
          aria-label="Date padding (days)"
          onChange={(e) => props.onPad(Number(e.target.value))}
        />
      </label>
      <label className="slider">
        <span className="slider-label">
          Review below confidence <output>{props.confidenceThreshold.toFixed(2)}</output>
        </span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={props.confidenceThreshold}
          aria-label="Confidence threshold"
          onChange={(e) => props.onConfidenceThreshold(Number(e.target.value))}
        />
      </label>
    </section>
  )
}
