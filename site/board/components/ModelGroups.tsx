"use client";

import { useState } from "react";
import { fmtPct } from "@/lib/format";
import {
  dimensionLabels, groupLabels, profileDimensions, type ProfileDimension,
} from "@/lib/profileLabels";
import type { modelProfile } from "@/lib/modelProfile";

type Observation = {
  rate: number;
  profile: ReturnType<typeof modelProfile>;
};

const notes: Record<ProfileDimension, string> = {
  kind: "Decision specialists are built for structured decisions. General-purpose models took the same test.",
  serving: "Local and hosted runs include different models. Their medians describe those groups. Measuring the effect of hosting would require running the same models both ways.",
  weights: "These groups describe access to model weights. A model can have downloadable weights even when Peira tested it through a hosted API. Unverified means the release status is unknown.",
  tier: "Peira’s frontier cohort includes named general-purpose baselines from OpenAI, Google, Anthropic, Moonshot, xAI, DeepSeek, Zhipu and MiniMax. The benchmark score plays no part in that designation.",
};

function groupRates(observations: Observation[], dimension: ProfileDimension) {
  const groups = new Map<string, number[]>();
  for (const { profile, rate } of observations) {
    const key = dimension === "tier" ? (profile.frontier ? "frontier" : "other") : profile[dimension];
    const rates = groups.get(key) ?? [];
    rates.push(rate);
    groups.set(key, rates);
  }
  return Object.entries(groupLabels[dimension]).flatMap(([key, label]) => {
    const rates = groups.get(key);
    if (!rates?.length) return [];
    rates.sort((a, b) => a - b);
    const middle = Math.floor(rates.length / 2);
    const median = rates.length % 2 ? rates[middle] : (rates[middle - 1] + rates[middle]) / 2;
    return [{ key, label, rates, median }];
  });
}

export default function ModelGroups({ observations }: { observations: Observation[] }) {
  const [dimension, setDimension] = useState<ProfileDimension>("kind");
  if (!observations.length) return null;
  const groups = groupRates(observations, dimension);
  const ceiling = Math.max(0.1, Math.ceil(Math.max(...observations.map(row => row.rate)) * 10) / 10);
  const position = (rate: number) => `${rate / ceiling * 100}%`;

  return (
    <section id="model-groups" className="model-groups" aria-labelledby="groups-title">
      <div className="group-intro">
        <h2 id="groups-title">Compare model groups</h2>
        <p>{notes[dimension]}</p>
        {dimension === "kind" && <a href="#explorer?pop=guards&mode=rank">View guard subset results</a>}
      </div>
      <div className="group-figure">
        <label className="group-choice">Group results by
          <select value={dimension} onChange={event => setDimension(event.target.value as ProfileDimension)}>
            {profileDimensions.map(key => <option key={key} value={key}>{dimensionLabels[key]}</option>)}
          </select>
        </label>
        <div className="group-columns" aria-hidden="true">
          <span>Ranked full suite</span><span>Attack success</span><span>Median</span>
        </div>
        <div aria-live="polite">
          {groups.map(({ key, label, rates, median }) => (
            <div className="group-row" key={key}>
              <div className="group-name">
                <a href={`#explorer?pop=full&mode=rank&${dimension}=${key}`}>{label}</a>
                <small>{rates.length} {rates.length === 1 ? "result" : "results"}</small>
              </div>
              <div className="group-track" role="img"
                aria-label={`Observed rates from ${fmtPct(rates[0])} to ${fmtPct(rates[rates.length - 1])}`}>
                {rates.map((rate, index) => <i key={index} style={{ left: position(rate) }} />)}
                <b style={{ left: position(median) }} />
              </div>
              <strong className="group-median" aria-label={`Median ${fmtPct(median)}`}>{fmtPct(median)}</strong>
            </div>
          ))}
        </div>
        <div className="group-columns group-axis" aria-hidden="true">
          <span /><span><span>0%</span><span>{Math.round(ceiling * 100)}%</span></span><span />
        </div>
        <p className="group-legend">Each tick represents one full-suite result. The diamond marks the median attack success rate. Lower is better.</p>
      </div>
    </section>
  );
}
