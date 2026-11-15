import { useEffect, useState } from 'react';
import { X, Code, FileText, Clock, User, GitBranch } from 'lucide-react';
import { toolApi } from '@/features/tools/api';
import { chatApi } from '@/features/projects/api/chat';
import type { ToolDetailResponse } from '@/features/tools/types';
import type { ToolApprovalResponse } from '@/features/projects/types/approval';
import type { ToolPlanDetailResponse } from '@/features/projects/types/chat';

interface ToolApprovalDetailModalProps {
  projectId: string;
  approvalItem: ToolApprovalResponse;
  onClose: () => void;
  onActionClick: (type: 'APPROVE' | 'REJECT') => void;
}

export function ToolApprovalDetailModal({
  projectId,
  approvalItem,
  onClose,
  onActionClick,
}: ToolApprovalDetailModalProps) {
  const canLoadPlanDetail = Boolean(approvalItem.toolPlanId && approvalItem.chatSessionId);
  const [toolDetail, setToolDetail] = useState<ToolDetailResponse | null>(null);
  const [toolPlanDetail, setToolPlanDetail] = useState<ToolPlanDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(approvalItem.toolId || canLoadPlanDetail));

  useEffect(() => {
    let isMounted = true;

    const fetchDetail = async () => {
      setToolDetail(null);
      setToolPlanDetail(null);

      if (approvalItem.toolPlanId) {
        if (!approvalItem.chatSessionId) {
          setIsLoading(false);
          return;
        }

        setIsLoading(true);
        try {
          const data = await chatApi.getToolPlanDetail(
            projectId,
            String(approvalItem.chatSessionId),
            String(approvalItem.toolPlanId),
          );
          if (isMounted) {
            setToolPlanDetail(data);
          }
        } catch (error) {
          console.error('Failed to fetch tool plan detail for approval', error);
        } finally {
          if (isMounted) {
            setIsLoading(false);
          }
        }
        return;
      }

      if (!approvalItem.toolId) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      try {
        if (!approvalItem.toolId) return;
        const data = await toolApi.getTool(projectId, approvalItem.toolId);
        if (isMounted) {
          setToolDetail(data);
        }
      } catch (error) {
        console.error('Failed to fetch tool detail for approval', error);
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };
    void fetchDetail();

    return () => {
      isMounted = false;
    };
  }, [projectId, approvalItem.chatSessionId, approvalItem.toolId, approvalItem.toolPlanId]);

  const approvalTitle =
    approvalItem.displayName ||
    approvalItem.fileName ||
    `ToolPlan #${approvalItem.toolPlanId ?? '-'}`;
  const planStatus =
    toolPlanDetail?.status || approvalItem.toolPlanStatus || approvalItem.toolStatus || '-';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-slate-800 bg-[#0b0e14] shadow-2xl duration-200 animate-in fade-in zoom-in-95">
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/50 px-6 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-slate-100">{approvalTitle}</h2>
            <span className="rounded border border-blue-500/30 bg-blue-500/20 px-2 py-1 text-[10px] font-medium tracking-wider text-blue-400 uppercase">
              {planStatus}
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-300"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <div className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
              상세 정보를 불러오는 중...
            </div>
          ) : (
            <div className="space-y-8">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <FileText className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">ToolPlan</span>
                  </div>
                  <p className="truncate font-mono text-sm text-slate-300">
                    {approvalItem.toolPlanId ?? '-'}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <User className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Requested By</span>
                  </div>
                  <p className="truncate text-sm text-slate-300">
                    {approvalItem.requestedByUserName}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <Clock className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Requested At</span>
                  </div>
                  <p className="truncate text-sm text-slate-300">
                    {new Date(approvalItem.requestedAt).toLocaleDateString()}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <GitBranch className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Version</span>
                  </div>
                  <p className="truncate text-sm text-slate-300">
                    v{approvalItem.planVersion ?? '-'}
                  </p>
                </div>
              </div>

              {/* Code/Artifact Viewer */}
              {approvalItem.toolPlanId ? (
                <div>
                  <div className="mb-3 flex items-center gap-2">
                    <FileText className="h-5 w-5 text-blue-400" />
                    <h3 className="text-sm font-medium tracking-wider text-slate-300 uppercase">
                      Tool Plan
                    </h3>
                  </div>
                  {toolPlanDetail ? (
                    <div className="space-y-4">
                      {toolPlanDetail.requestedPrompt && (
                        <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                          <div className="mb-2 text-xs tracking-wider text-slate-500 uppercase">
                            Request
                          </div>
                          <p className="text-sm whitespace-pre-wrap text-slate-300">
                            {toolPlanDetail.requestedPrompt}
                          </p>
                        </div>
                      )}
                      <div className="overflow-hidden rounded-lg border border-slate-800 bg-[#1e1e1e]">
                        <pre className="scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent max-h-[50vh] overflow-auto p-4 font-mono text-sm whitespace-pre-wrap text-slate-300">
                          <code>
                            {toolPlanDetail.rawMarkdown || 'ToolPlan 원문이 비어 있습니다.'}
                          </code>
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-slate-800 bg-[#1e1e1e] p-6 text-center">
                      <p className="mb-2 text-sm text-slate-400">
                        ToolPlan 상세 정보를 불러올 수 없습니다.
                      </p>
                      <p className="text-xs text-slate-500">
                        승인 요청 응답의 chatSessionId와 toolPlanId를 확인해 주세요.
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div>
                  <div className="mb-3 flex items-center gap-2">
                    <Code className="h-5 w-5 text-blue-400" />
                    <h3 className="text-sm font-medium tracking-wider text-slate-300 uppercase">
                      Python Code
                    </h3>
                  </div>
                  <div className="overflow-hidden rounded-lg border border-slate-800 bg-[#1e1e1e]">
                    <pre className="scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent max-h-[50vh] overflow-auto p-4 font-mono text-sm text-slate-300">
                      <code>
                        {toolDetail
                          ? toolDetail.codeSnapshot || '# 파이썬 코드 정보를 불러올 수 없습니다.'
                          : '# 파이썬 코드 정보를 불러올 수 없습니다.'}
                      </code>
                    </pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-800 bg-slate-900/50 px-6 py-4">
          <div className="text-xs text-slate-500">
            ToolPlan 내용을 확인한 뒤 승인 또는 반려를 진행하세요.
          </div>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="rounded px-4 py-2 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
            >
              닫기
            </button>
            {approvalItem.approvalStatus === 'PENDING' && (
              <>
                <button
                  onClick={() => onActionClick('REJECT')}
                  className="rounded border border-red-500/20 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/20"
                >
                  반려
                </button>
                <button
                  onClick={() => onActionClick('APPROVE')}
                  className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-blue-900/20 transition-colors hover:bg-blue-500"
                >
                  승인
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
