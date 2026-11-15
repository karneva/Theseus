import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { CheckCircle2, XCircle, Clock, Eye } from 'lucide-react';
import { approvalApi } from '@/features/projects/api/approval';
import type { ToolApprovalResponse } from '@/features/projects/types/approval';
import { getApiErrorMessage } from '@/api/errors';
import { ToolApprovalDetailModal } from './ToolApprovalDetailModal';
import {
  DEFAULT_MEMBER_ACCESS_LEVEL,
  MAX_MEMBER_ACCESS_LEVEL,
  clampMemberAccessLevel,
} from '../../utils/memberPolicy';

/**
 * 도구 등급은 "이 등급 이상의 멤버 접근 레벨만 사용 가능"을 뜻한다. 백엔드는 승인 시
 * ProjectAccessLevelPolicy.isMemberAccessLevel(1..5)로 검증하므로 멤버 접근 레벨과 같은 범위를 쓴다.
 * 범위를 넘으면 어떤 멤버도 쓸 수 없는 도구가 만들어지므로 입력 단계에서 막는다.
 */
const DEFAULT_TOOL_GRADE = DEFAULT_MEMBER_ACCESS_LEVEL;
const MAX_TOOL_GRADE = MAX_MEMBER_ACCESS_LEVEL;

interface ToolApprovalManagementProps {
  projectId: string;
}

export function ToolApprovalManagement({ projectId }: ToolApprovalManagementProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const filterStatus = searchParams.get('status') || 'PENDING';

  const setFilterStatus = (status: string) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('status', status);
        return next;
      },
      { replace: true },
    );
  };

  const [approvals, setApprovals] = useState<ToolApprovalResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // States for Detail Modal
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [selectedDetailApproval, setSelectedDetailApproval] = useState<ToolApprovalResponse | null>(
    null,
  );

  // States for Approve/Reject Dialog
  const [isActionOpen, setIsActionOpen] = useState(false);
  const [selectedApproval, setSelectedApproval] = useState<ToolApprovalResponse | null>(null);
  const [actionType, setActionType] = useState<'APPROVE' | 'REJECT'>('APPROVE');

  // Form states
  const [toolGrade, setToolGrade] = useState<number>(DEFAULT_TOOL_GRADE);
  const [reviewFeedback, setReviewFeedback] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  // 승인/반려 성공 후 목록을 서버 기준으로 다시 불러오기 위한 트리거
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const fetchApprovals = async () => {
      setIsLoading(true);
      try {
        const statusParam = filterStatus === 'ALL' ? undefined : filterStatus;
        const res = await approvalApi.getToolApprovals(projectId, 0, 50, statusParam);
        if (cancelled) return;
        setApprovals(res.content || []);
      } catch (err) {
        if (!cancelled) console.error('Failed to fetch tool approvals', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void fetchApprovals();
    return () => {
      cancelled = true;
    };
  }, [projectId, filterStatus, reloadKey]);

  const openDetailModal = (approval: ToolApprovalResponse) => {
    setSelectedDetailApproval(approval);
    setIsDetailOpen(true);
  };

  const openActionModal = (approval: ToolApprovalResponse, type: 'APPROVE' | 'REJECT') => {
    setSelectedApproval(approval);
    setActionType(type);
    setToolGrade(DEFAULT_TOOL_GRADE);
    setReviewFeedback('');
    setIsActionOpen(true);
  };

  const handleDetailActionClick = (type: 'APPROVE' | 'REJECT') => {
    if (selectedDetailApproval) {
      setIsDetailOpen(false);
      openActionModal(selectedDetailApproval, type);
    }
  };

  /**
   * 승인/반려를 실제 API로 반영한다.
   * - 승인: PATCH .../approve { toolGrade, reviewFeedback }. ToolPlan 승인이면 백엔드가 BUILD run을 만들고,
   *   빌드 진행 상황은 채팅 세션의 BUILD SSE로 보여 준다(여기서는 승인 결과만 다룬다).
   * - 반려: PATCH .../reject { reviewFeedback }. 반려 사유는 필수다.
   * 성공하면 로컬 목록을 손으로 고치지 않고 서버에서 다시 조회해, 새로고침해도 같은 상태가 보이게 한다.
   */
  const handleActionSubmit = async () => {
    if (!selectedApproval) return;

    const feedback = reviewFeedback.trim();
    if (actionType === 'REJECT' && !feedback) {
      toast.warning('반려 사유를 입력해주세요.');
      return;
    }

    setIsSubmitting(true);
    try {
      if (actionType === 'APPROVE') {
        await approvalApi.approveTool(projectId, selectedApproval.toolApprovalId, {
          toolGrade: clampMemberAccessLevel(toolGrade),
          reviewFeedback: feedback || undefined,
        });
        toast.success(
          selectedApproval.toolPlanId
            ? '승인되었습니다. 도구 빌드가 시작됩니다.'
            : '도구가 승인되었습니다.',
        );
      } else {
        await approvalApi.rejectTool(projectId, selectedApproval.toolApprovalId, {
          reviewFeedback: feedback,
        });
        toast.success('도구가 반려되었습니다.');
      }
      setIsActionOpen(false);
      setReloadKey((key) => key + 1);
    } catch (err) {
      console.error('Tool approval action failed', err);
      toast.error(getApiErrorMessage(err, '처리에 실패했습니다.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'PENDING':
        return <Clock className="h-3 w-3 text-amber-500" />;
      case 'APPROVED':
        return <CheckCircle2 className="h-3 w-3 text-green-500" />;
      case 'REJECTED':
        return <XCircle className="h-3 w-3 text-red-500" />;
      default:
        return null;
    }
  };

  return (
    <>
      <Card className="overflow-x-auto border-slate-800 bg-slate-900/40 shadow-2xl shadow-blue-500/5 backdrop-blur-xl">
        <CardHeader className="mb-6 flex min-w-[900px] flex-row items-center justify-between border-b border-slate-800/50">
          <div className="min-w-max">
            <CardTitle className="mb-1 font-['Space_Grotesk'] whitespace-nowrap text-white">
              도구 승인 대기열
            </CardTitle>
            <CardDescription className="whitespace-nowrap text-slate-400">
              멤버들이 생성 요청한 도구를 검토하고 승인합니다.
            </CardDescription>
          </div>

          <div className="flex items-center gap-3">
            <Label className="text-[10px] font-bold tracking-wider text-slate-400 uppercase">
              필터
            </Label>
            <Select value={filterStatus} onValueChange={setFilterStatus}>
              <SelectTrigger className="w-[140px] border-slate-800 bg-slate-950/50 text-slate-200">
                <SelectValue placeholder="상태 필터" />
              </SelectTrigger>
              <SelectContent className="border-slate-800 bg-slate-900 text-white">
                <SelectItem value="ALL">전체 보기</SelectItem>
                <SelectItem value="PENDING">대기 중</SelectItem>
                <SelectItem value="APPROVED">승인됨</SelectItem>
                <SelectItem value="REJECTED">반려됨</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>

        <CardContent>
          {isLoading ? (
            <div className="animate-pulse py-12 text-center text-slate-500">
              요청 목록을 불러오는 중...
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/20">
              <Table className="min-w-[900px]">
                <TableHeader className="bg-slate-950/50">
                  <TableRow className="border-slate-800 hover:bg-transparent">
                    <TableHead className="text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                      도구 이름 / 유형
                    </TableHead>
                    <TableHead className="text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                      요청자
                    </TableHead>
                    <TableHead className="text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                      상태
                    </TableHead>
                    <TableHead className="text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                      요청일
                    </TableHead>
                    <TableHead className="text-right text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                      작업
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {approvals.length === 0 ? (
                    <TableRow className="border-slate-800">
                      <TableCell
                        colSpan={5}
                        className="py-12 text-center font-medium text-slate-500"
                      >
                        대기 중인 승인 요청이 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : (
                    approvals.map((approval) => (
                      <TableRow
                        key={approval.toolApprovalId}
                        className="border-slate-800 transition-colors hover:bg-slate-900/40"
                      >
                        <TableCell>
                          <div className="font-bold text-slate-200">
                            {approval.displayName ||
                              approval.fileName ||
                              `설계안 #${approval.toolPlanId ?? '-'}`}
                            {approval.toolPlanId && (
                              <span className="ml-2 rounded border border-blue-400/30 px-1 py-0.5 text-[10px] font-normal text-blue-400">
                                설계안
                              </span>
                            )}
                          </div>
                          <div className="mt-0.5 font-mono text-[10px] tracking-wider text-blue-400 uppercase">
                            {approval.toolPlanStatus || approval.toolStatus || '-'}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="text-sm font-medium text-slate-300">
                            {approval.requestedByUserName}
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            {getStatusIcon(approval.approvalStatus)}
                            <Badge
                              variant="outline"
                              className={cn(
                                'text-[10px] font-bold uppercase',
                                approval.approvalStatus === 'PENDING'
                                  ? 'border-amber-900 bg-amber-950/30 text-amber-400'
                                  : approval.approvalStatus === 'APPROVED'
                                    ? 'border-green-900 bg-green-950/30 text-green-400'
                                    : 'border-red-900 bg-red-950/30 text-red-400',
                              )}
                            >
                              {approval.approvalStatus}
                            </Badge>
                          </div>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-slate-500">
                          {new Date(approval.requestedAt).toLocaleDateString()}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              className="border-slate-800 bg-slate-900/40 text-[11px] font-bold text-slate-400 transition-all hover:bg-slate-800 hover:text-slate-100"
                              onClick={() => openDetailModal(approval)}
                            >
                              <Eye className="mr-1.5 h-3 w-3" />
                              상세 보기
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>

        <Dialog
          open={isActionOpen}
          onOpenChange={(open) => {
            if (!isSubmitting) setIsActionOpen(open);
          }}
        >
          <DialogContent className="max-w-lg border-slate-800 bg-[#0b1424] text-slate-100">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-white">
                <Clock className="h-5 w-5 text-blue-400" /> 도구 승인 검토
              </DialogTitle>
              <DialogDescription className="font-medium text-slate-400">
                <span className="font-bold text-blue-400">
                  {selectedApproval?.displayName || selectedApproval?.fileName || '도구/설계안'}
                </span>
                에 대한 승인 요청을 검토합니다.
              </DialogDescription>
            </DialogHeader>

            {isSubmitting ? (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400">
                <div className="mb-6 h-12 w-12 animate-spin rounded-full border-4 border-slate-800 border-t-blue-500" />
                <p className="px-4 text-center text-sm font-medium text-slate-300">
                  {actionType === 'APPROVE' ? '승인 처리 중입니다...' : '반려 처리 중입니다...'}
                </p>
              </div>
            ) : (
              <>
                <div className="space-y-6 py-6">
                  <div className="space-y-4">
                    <Label className="text-[10px] font-bold tracking-widest text-slate-300 uppercase">
                      승인 결정
                    </Label>
                    <div className="flex gap-4">
                      <Button
                        variant={actionType === 'APPROVE' ? 'default' : 'outline'}
                        onClick={() => setActionType('APPROVE')}
                        className={cn(
                          'flex-1 font-bold',
                          actionType === 'APPROVE'
                            ? 'bg-green-600 text-white hover:bg-green-700'
                            : 'border-slate-800 text-slate-500 hover:bg-slate-900',
                        )}
                      >
                        승인 (Approve)
                      </Button>
                      <Button
                        variant={actionType === 'REJECT' ? 'default' : 'outline'}
                        onClick={() => setActionType('REJECT')}
                        className={cn(
                          'flex-1 font-bold',
                          actionType === 'REJECT'
                            ? 'bg-red-600 text-white hover:bg-red-700'
                            : 'border-slate-800 text-slate-500 hover:bg-slate-900',
                        )}
                      >
                        반려 (Reject)
                      </Button>
                    </div>
                  </div>

                  {actionType === 'APPROVE' && !selectedApproval?.toolPlanId && (
                    <div className="space-y-2">
                      <Label className="text-[10px] font-bold tracking-widest text-slate-300 uppercase">
                        도구 등급 (Tool Grade)
                      </Label>
                      <Input
                        type="number"
                        min={DEFAULT_TOOL_GRADE}
                        max={MAX_TOOL_GRADE}
                        value={toolGrade}
                        onChange={(e) =>
                          setToolGrade(clampMemberAccessLevel(Number(e.target.value)))
                        }
                        className="border-slate-800 bg-slate-950 text-white"
                      />
                      <p className="text-[11px] text-slate-500">
                        허용 범위: {DEFAULT_TOOL_GRADE}-{MAX_TOOL_GRADE} (이 등급 이상의 접근 레벨을
                        가진 멤버만 사용할 수 있습니다)
                      </p>
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label className="text-[10px] font-bold tracking-widest text-slate-300 uppercase">
                      검토 의견
                    </Label>
                    <Textarea
                      placeholder={
                        actionType === 'APPROVE'
                          ? '승인 사유를 입력하세요...'
                          : '반려 사유를 입력하세요...'
                      }
                      value={reviewFeedback}
                      onChange={(e) => setReviewFeedback(e.target.value)}
                      className="min-h-[100px] border-slate-800 bg-slate-950 text-white"
                    />
                  </div>
                </div>

                <DialogFooter className="gap-2">
                  <Button
                    variant="outline"
                    onClick={() => setIsActionOpen(false)}
                    className="border-slate-700 text-slate-300 hover:bg-slate-800"
                  >
                    취소
                  </Button>
                  <Button
                    onClick={handleActionSubmit}
                    className={cn(
                      'px-8 font-bold',
                      actionType === 'APPROVE'
                        ? 'bg-green-600 text-white hover:bg-green-700'
                        : 'bg-red-600 text-white hover:bg-red-700',
                    )}
                  >
                    {actionType === 'APPROVE' ? '승인하기' : '반려하기'}
                  </Button>
                </DialogFooter>
              </>
            )}
          </DialogContent>
        </Dialog>
      </Card>

      {isDetailOpen && selectedDetailApproval && (
        <ToolApprovalDetailModal
          projectId={projectId}
          approvalItem={selectedDetailApproval}
          onClose={() => setIsDetailOpen(false)}
          onActionClick={handleDetailActionClick}
        />
      )}
    </>
  );
}
