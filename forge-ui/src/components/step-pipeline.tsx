export interface PipelineStage {
  id: string;
  label: string;
  status: "pending" | "running" | "success" | "error" | "skipped";
  detail?: string;
}

interface StepPipelineProps {
  stages: PipelineStage[];
}

const STATUS_STYLES: Record<
  PipelineStage["status"],
  { dot: string; text: string; line: string }
> = {
  pending: {
    dot: "bg-card-border",
    text: "text-muted",
    line: "bg-card-border",
  },
  running: {
    dot: "bg-cam-blue animate-pulse",
    text: "text-cam-blue",
    line: "bg-cam-blue/30",
  },
  success: {
    dot: "bg-cam-green",
    text: "text-cam-green",
    line: "bg-cam-green/30",
  },
  error: {
    dot: "bg-red-500",
    text: "text-red-400",
    line: "bg-red-500/30",
  },
  skipped: {
    dot: "bg-muted-dark",
    text: "text-muted-dark",
    line: "bg-card-border",
  },
};

export function StepPipeline({ stages }: StepPipelineProps) {
  return (
    <div className="space-y-0">
      {stages.map((stage, i) => {
        const style = STATUS_STYLES[stage.status];
        const isLast = i === stages.length - 1;
        return (
          <div key={stage.id} className="flex gap-3">
            {/* Dot + connector line */}
            <div className="flex flex-col items-center">
              <div
                className={`w-3 h-3 rounded-full shrink-0 mt-1 ${style.dot}`}
              />
              {!isLast && (
                <div className={`w-0.5 flex-1 min-h-[24px] ${style.line}`} />
              )}
            </div>
            {/* Content */}
            <div className="pb-4">
              <div className={`text-sm font-medium ${style.text}`}>
                {stage.label}
              </div>
              {stage.detail && (
                <div className="text-xs text-muted mt-0.5">{stage.detail}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
