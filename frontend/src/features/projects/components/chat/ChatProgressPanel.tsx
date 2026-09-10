interface ChatProgressPanelProps {
  title: string;
  message?: string;
  log: string;
}

export function ChatProgressPanel({ title, message, log }: ChatProgressPanelProps) {
  return (
    <div className="flex justify-start animate-in fade-in slide-in-from-bottom-2 duration-300">
      <div className="w-full max-w-[85%] bg-slate-900/40 border border-blue-500/20 rounded-xl overflow-hidden shadow-2xl backdrop-blur-sm">
        <div className="bg-blue-500/10 px-4 py-2 border-b border-blue-500/10 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="flex gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" />
              <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce [animation-delay:0.2s]" />
              <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce [animation-delay:0.4s]" />
            </div>
            <span className="text-[10px] font-bold text-blue-400 uppercase tracking-[0.2em]">
              {title}
            </span>
          </div>
        </div>
        <div className="p-4 space-y-3">
          {message && (
            <div className="text-sm text-blue-100/90 font-medium leading-relaxed">{message}</div>
          )}
          <div className="bg-[#050c18] rounded-lg p-3 border border-slate-800/50">
            <div className="font-mono text-[11px] leading-relaxed text-slate-400 break-all max-h-[150px] overflow-y-auto scrollbar-none">
              <span className="text-blue-500/50 mr-2">$</span>
              {log}
              <span className="inline-block w-1.5 h-3.5 bg-blue-500/50 ml-1 animate-pulse" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
