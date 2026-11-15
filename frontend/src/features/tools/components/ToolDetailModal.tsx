import { getApiErrorMessage } from '@/api/errors';
import { useState, useEffect } from 'react';
import { X, Code, FileText, CheckCircle, Clock, Trash2, Shield } from 'lucide-react';
import { toolApi } from '../api';
import type { ToolDetailResponse, ToolItem } from '../types';

interface ToolDetailModalProps {
  projectId: string;
  toolItem: ToolItem;
  onClose: () => void;
  onDeleteSuccess?: () => void;
}

export function ToolDetailModal({
  projectId,
  toolItem,
  onClose,
  onDeleteSuccess,
}: ToolDetailModalProps) {
  const [detail, setDetail] = useState<ToolDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);

  const handleDelete = async () => {
    if (
      !window.confirm('정말 이 도구를 삭제하시겠습니까? 삭제 후에는 도구 목록에서 보이지 않습니다.')
    ) {
      return;
    }

    setIsDeleting(true);
    try {
      await toolApi.deleteTool(projectId, toolItem.toolId);
      alert('도구가 성공적으로 삭제되었습니다.');
      if (onDeleteSuccess) {
        onDeleteSuccess();
      }
      onClose();
    } catch (err: unknown) {
      console.error('Failed to delete tool:', err);
      alert(getApiErrorMessage(err, '도구 삭제에 실패했습니다.'));
    } finally {
      setIsDeleting(false);
    }
  };

  useEffect(() => {
    let isMounted = true;
    const fetchDetail = async () => {
      setIsLoading(true);
      try {
        const data = await toolApi.getTool(projectId, toolItem.toolId);
        if (isMounted) {
          setDetail(data);
        }
      } catch (error) {
        console.error('Failed to fetch tool detail', error);
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };
    void fetchDetail();
    return () => {
      isMounted = false;
    };
  }, [projectId, toolItem.toolId]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />

      <div className="relative flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-slate-800 bg-[#0b0e14] shadow-2xl duration-200 animate-in fade-in zoom-in-95">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/50 px-6 py-4">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-slate-100">{toolItem.displayName}</h2>
            {detail && (
              <span className="rounded bg-slate-800 px-2 py-1 text-[10px] font-medium tracking-wider text-slate-400 uppercase">
                PLAN #{detail.sourceToolPlanId ?? '-'}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-800 hover:text-slate-300"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent flex-1 overflow-y-auto p-6">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-20 text-slate-500">
              <div className="mb-4 h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
              상세 정보를 불러오는 중...
            </div>
          ) : detail ? (
            <div className="space-y-8">
              {/* Meta Info */}
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <FileText className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">File Name</span>
                  </div>
                  <p className="truncate font-mono text-sm text-slate-300">{detail.fileName}</p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <CheckCircle className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Status</span>
                  </div>
                  <p className="text-sm text-slate-300">{detail.status}</p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <Clock className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Created At</span>
                  </div>
                  <p className="truncate text-sm text-slate-300">
                    {new Date(detail.createdAt).toLocaleDateString()}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <Clock className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Updated At</span>
                  </div>
                  <p className="truncate text-sm text-slate-300">
                    {new Date(detail.updatedAt).toLocaleDateString()}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <Shield className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Access Level</span>
                  </div>
                  <p className="text-sm text-slate-300">Lv.{detail.toolGrade ?? 1}</p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <Code className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Module</span>
                  </div>
                  <p className="truncate font-mono text-sm text-slate-300">
                    {detail.moduleName || '-'}
                  </p>
                </div>
                <div className="rounded-lg border border-slate-800/50 bg-slate-900/50 p-4">
                  <div className="mb-1 flex items-center gap-2 text-slate-500">
                    <FileText className="h-4 w-4" />
                    <span className="text-xs tracking-wider uppercase">Artifact</span>
                  </div>
                  <p className="truncate font-mono text-sm text-slate-300">
                    {detail.artifactPath || '-'}
                  </p>
                </div>
              </div>

              {/* Code Viewer */}
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
                      {detail.codeSnapshot ||
                        detail.metadataJson ||
                        '# 생성된 코드 정보를 불러올 수 없습니다.'}
                    </code>
                  </pre>
                </div>
              </div>
            </div>
          ) : (
            <div className="py-20 text-center text-slate-500">
              도구 상세 정보를 찾을 수 없습니다.
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between border-t border-slate-800 bg-slate-900/50 px-6 py-4">
          <button
            onClick={handleDelete}
            disabled={isDeleting || isLoading}
            className="flex items-center gap-2 rounded border border-rose-500/20 px-4 py-2 text-sm font-medium text-rose-400 transition-all hover:border-rose-500/40 hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-4 w-4" />
            {isDeleting ? '삭제 중...' : '도구 삭제'}
          </button>

          <button
            onClick={onClose}
            className="rounded px-4 py-2 text-sm font-medium text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200"
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  );
}
