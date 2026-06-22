import React from "react";

export interface MetricCardData {
  label: string;
  value: string;
  sub?: string;
}

interface MetricsRowProps {
  metrics: MetricCardData[];
}

export default function MetricsRow({ metrics }: MetricsRowProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-[10px] w-full">
      {metrics.map((m, idx) => (
        <div
          key={idx}
          className="bg-tm-surface rounded-[8px] p-[12px_14px] flex flex-col justify-between select-none"
        >
          <span className="text-[11px] uppercase tracking-[0.05em] text-tm-muted leading-none">
            {m.label}
          </span>
          <div className="mt-2 flex items-baseline gap-1.5">
            <span className="text-[22px] font-medium text-tm-text leading-none">
              {m.value}
            </span>
            {m.sub && (
              <span className="text-[11px] text-tm-muted">
                {m.sub}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
