import { OUTCOMES, OUTCOME_LABEL, type Consensus } from '../api/types'

/** 폴리마켓식 확률 막대. 지분 비율을 그대로 확률로 보여준다. */
export function OddsBar({ consensus }: { consensus: Consensus }) {
  return (
    <div className="odds">
      {OUTCOMES.map((outcome) => {
        const p = consensus.probabilities[outcome] ?? 0
        return (
          <div className="odds-row" key={outcome}>
            <span className={`badge ${outcome}`}>{OUTCOME_LABEL[outcome]}</span>
            <div className="odds-track">
              <div
                className={`odds-fill ${outcome}`}
                style={{ width: `${Math.round(p * 100)}%` }}
              />
            </div>
            <span className="odds-pct">{Math.round(p * 100)}%</span>
          </div>
        )
      })}
    </div>
  )
}
