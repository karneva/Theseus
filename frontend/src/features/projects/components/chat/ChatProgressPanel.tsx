interface ChatProgressPanelProps {
  title: string;
  message?: string;
  log: string;
}

export function ChatProgressPanel({ title, message, log }: ChatProgressPanelProps) {
  return (
    <div className="flex justify-start duration-300 animate-in fade-in slide-in-from-bottom-2">
      <div className="w-full max-w-[85%] overflow-hidden rounded-xl border border-blue-500/20 bg-slate-900/40 shadow-2xl backdrop-blur-sm">
        <div className="flex items-center justify-between border-b border-blue-500/10 bg-blue-500/10 px-4 py-2">
          <div className="flex items-center gap-2.5">
            <div className="flex gap-1">
              <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-500" />
              <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-500 [animation-delay:0.2s]" />
              <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-blue-500 [animation-delay:0.4s]" />
            </div>
            <span className="text-[10px] font-bold tracking-[0.2em] text-blue-400 uppercase">
              {title}
            </span>
          </div>
        </div>
        <div className="space-y-3 p-4">
          {message && (
            <div className="text-sm leading-relaxed font-medium text-blue-100/90">{message}</div>
          )}
          <div className="rounded-lg border border-slate-800/50 bg-[#050c18] p-3">
            <div className="scrollbar-none max-h-[150px] overflow-y-auto font-mono text-[11px] leading-relaxed break-all text-slate-400">
              <span className="mr-2 text-blue-500/50">$</span>
              {log}
              <span className="ml-1 inline-block h-3.5 w-1.5 animate-pulse bg-blue-500/50" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
