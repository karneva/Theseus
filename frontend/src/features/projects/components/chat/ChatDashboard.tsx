import { ChatArea } from './ChatArea';
import { InspectorPanel } from './InspectorPanel';

export function ChatDashboard() {
  return (
    <div className="scrollbar-thin scrollbar-thumb-slate-800 scrollbar-track-transparent flex h-full w-full overflow-x-auto overflow-y-hidden bg-[#051424] text-slate-200">
      {/* Center: Chat Area */}
      <div className="relative flex h-full min-w-[500px] flex-1 flex-col">
        <ChatArea />
      </div>

      {/* Right: Inspector / Plan Panel */}
      <div className="relative flex h-full w-[380px] min-w-[380px] flex-shrink-0 flex-col border-l border-slate-800 bg-[#0b0e14]/60 backdrop-blur-md">
        <InspectorPanel />
      </div>
    </div>
  );
}
