import { useId } from "react";

type TokenSample = {
  estimated_tokens?: number | null;
  baseline_tokens?: number | null;
  sections: { name: string; tokens: number }[];
};

const format = new Intl.NumberFormat("es", { maximumFractionDigits: 1 });
const colors = ["#6289db", "#36a18f", "#a475d7", "#cc8f45", "#d7799c", "#4e9fc4",
  "#8d9e51", "#a67b65", "#7a869c", "#be6c5b", "#8070b4", "#5791a0"];

function TokenFlow({ branches, total, estimated }: {
  branches: { label: string; tokens: number }[];
  total: number;
  estimated: number;
}) {
  const titleId = useId();
  const height = 128;
  const gap = 9;
  const span = height + (branches.length - 1) * gap;
  const sourceY = (span - height) / 2;
  let y = 0;

  return <figure className="context-chart">
    <figcaption id={titleId}>Reparto de tokens · Sankey</figcaption>
    <p className="context-chart-total"><strong>{format.format(total)}</strong> tokens {total === estimated ? "estimados" : "por secciones"}</p>
    <svg className="context-sankey" viewBox={`0 0 400 ${span}`} role="img" aria-labelledby={titleId}>
      <rect x="0" y={sourceY} width="9" height={height} rx="2" fill="var(--blue)"/>
      {branches.map(({ label, tokens }, index) => {
        const thickness = tokens * height / total;
        const from = sourceY + y;
        const to = y + index * gap;
        y += thickness;
        const color = colors[index % colors.length];
        return <g key={label} fill={color}>
          <title>{label} · {format.format(tokens)} tokens</title>
          <path opacity=".62" d={`M9 ${from} C145 ${from} 255 ${to} 391 ${to}
            v${thickness} C255 ${to + thickness} 145 ${from + thickness} 9 ${from + thickness} Z`}/>
          <rect x="391" y={to} width="9" height={thickness}/>
        </g>;
      })}
    </svg>
    <ul className="context-sankey-legend">
      {branches.map(({ label, tokens }, index) => <li key={label}>
        <i style={{ backgroundColor: colors[index % colors.length] }} aria-hidden="true"/>
        <span>{label}</span><strong>{format.format(tokens)}</strong>
      </li>)}
    </ul>
    {total > estimated && <p className="context-chart-note">
      El contexto completo se estimó en {format.format(estimated)} tokens. El recuento por sección se calcula por separado.
    </p>}
  </figure>;
}

export function ContextMetricCharts({ samples, names }: {
  samples: TokenSample[];
  names: Record<string, string>;
}) {
  const sections = new Map<string, number>();
  let estimated = 0;
  let baseline = 0;
  let comparable = 0;
  let comparisons = 0;
  for (const sample of samples) {
    if (sample.estimated_tokens == null) continue;
    estimated += sample.estimated_tokens;
    for (const { name, tokens } of sample.sections) {
      if (tokens > 0) sections.set(name, (sections.get(name) ?? 0) + tokens);
    }
    if (sample.baseline_tokens != null) {
      baseline += sample.baseline_tokens;
      comparable += sample.estimated_tokens;
      comparisons++;
    }
  }
  const recorded = [...sections.values()].reduce((sum, tokens) => sum + tokens, 0);
  const branches = [...sections].map(([name, tokens]) => ({ label: names[name] ?? name, tokens }))
    .sort((a, b) => b.tokens - a.tokens);
  if (recorded < estimated) {
    branches.push({ label: "Resto del contexto", tokens: estimated - recorded });
  }
  const total = Math.max(recorded, estimated);
  const savings = baseline - comparable;
  const scale = Math.max(1, baseline, comparable);
  const bars = [
    { label: "Base sin optimizar", value: baseline, tone: "baseline" },
    { label: "Contexto generado", value: comparable, tone: "generated" },
    { label: savings < 0 ? "Exceso estimado" : "Ahorro estimado", value: Math.abs(savings),
      tone: savings < 0 ? "excess" : "saved" },
  ];

  return <div className="context-metric-charts">
    {total > 0
      ? <TokenFlow branches={branches} total={total} estimated={estimated}/>
      : <figure className="context-chart"><figcaption>Reparto de tokens · Sankey</figcaption>
        <p className="context-chart-note">Aún no hay estimaciones de contexto para graficar.</p>
      </figure>}
    <figure className="context-chart">
      <figcaption>Total frente al ahorro</figcaption>
      {comparisons > 0 ? <>
        <dl className="context-token-bars">
          {bars.map(({ label, value, tone }) => <div key={tone}>
            <dt>{label}</dt><dd>{format.format(value)} tokens</dd>
            <div className="context-token-track" aria-hidden="true">
              <span className={`context-token-fill ${tone}`} style={{ width: `${100 * value / scale}%` }}/>
            </div>
          </div>)}
        </dl>
        <p className="context-chart-note">
          {baseline > 0 && `${format.format(100 * Math.abs(savings) / baseline)} % de ${savings < 0 ? "exceso" : "ahorro"} · `}
          {comparisons} {comparisons === 1 ? "muestra con ambas estimaciones" : "muestras con ambas estimaciones"}
        </p>
      </> : <p className="context-chart-note">Aún no hay muestras con una base y un contexto estimados.</p>}
    </figure>
  </div>;
}
