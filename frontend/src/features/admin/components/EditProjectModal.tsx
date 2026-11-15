import { getApiErrorMessage } from '@/api/errors';
import { useState } from 'react';
import { adminApi } from '../api';
import type { UserResponse, ProjectSummaryResponse } from '../api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface EditProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  project: ProjectSummaryResponse | null;
}

export default function EditProjectModal({
  isOpen,
  onClose,
  onSuccess,
  project,
}: EditProjectModalProps) {
  const [formState, setFormState] = useState({
    projectName: project?.name || '',
    description: project?.description || '',
    employeeNumber: project?.projectAdminEmployeeNumber || '',
    searchedUser: project
      ? ({
          id: project.projectAdminUserId,
          employeeNumber: project.projectAdminEmployeeNumber,
          name: project.projectAdminName,
          email: '',
          systemRole: 'USER',
          status: 'ACTIVE',
        } as UserResponse)
      : null,
  });
  const [isSearching, setIsSearching] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  const { projectName, description, employeeNumber, searchedUser } = formState;

  const handleSearch = async () => {
    const trimmedId = employeeNumber.trim();
    if (!trimmedId) return;

    setIsSearching(true);
    try {
      const user = await adminApi.searchUserByEmployeeNumber(trimmedId);
      if (user && user.systemRole !== 'SUPER_ADMIN') {
        setFormState((prev) => ({ ...prev, searchedUser: user }));
      } else {
        alert('사용자를 찾을 수 없습니다.');
        setFormState((prev) => ({ ...prev, searchedUser: null }));
      }
    } catch (error: unknown) {
      console.error('Search failed:', error);
      const message = getApiErrorMessage(error, '사용자를 찾을 수 없습니다.');
      alert(message);
      setFormState((prev) => ({ ...prev, searchedUser: null }));
    } finally {
      setIsSearching(false);
    }
  };

  const handleUpdate = async () => {
    if (!project || !projectName || !searchedUser) return;
    setIsUpdating(true);
    try {
      await adminApi.updateProject(project.projectId, {
        name: projectName,
        description: description,
        adminEmployeeNumber: searchedUser.employeeNumber,
        adminName: searchedUser.name,
      });
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Failed to update project:', error);
      alert('프로젝트 수정에 실패했습니다.');
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="overflow-hidden rounded-[8px] border-[#1f2937] bg-[#1c2b3c] p-0 text-white shadow-[0px_20px_50px_0px_rgba(0,0,0,0.5)] sm:max-w-[448px]">
        <DialogHeader className="border-b border-[rgba(65,71,81,0.3)] px-8 pt-8 pb-6">
          <DialogTitle className="font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[20px] tracking-[-0.5px] text-white">
            프로젝트 수정
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-6 px-8 py-6">
          <div className="flex flex-col gap-2">
            <Label className="font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[12px] tracking-[0.6px] text-[#c1c7d3] uppercase">
              프로젝트 명
            </Label>
            <Input
              value={projectName}
              onChange={(e) => setFormState((prev) => ({ ...prev, projectName: e.target.value }))}
              placeholder="프로젝트 명 입력"
              className="h-[48px] border-[#414751] bg-[#010f1f] px-[17px] text-[14px] text-[#d4e4fa]"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label className="font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[12px] tracking-[0.6px] text-[#c1c7d3] uppercase">
              프로젝트 설명
            </Label>
            <Input
              value={description}
              onChange={(e) => setFormState((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="프로젝트 설명 입력"
              className="h-[48px] border-[#414751] bg-[#010f1f] px-[17px] text-[14px] text-[#d4e4fa]"
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label className="font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[12px] tracking-[0.6px] text-[#c1c7d3] uppercase">
              담당자 사번
            </Label>
            <div className="relative flex items-center">
              <Input
                value={employeeNumber}
                onChange={(e) => {
                  setFormState((prev) => ({
                    ...prev,
                    employeeNumber: e.target.value,
                    searchedUser: null,
                  }));
                }}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="담당자 사번 입력"
                className="h-[48px] w-full border-[#414751] bg-[#010f1f] px-[17px] pr-[60px] text-[14px] text-[#d4e4fa] focus-visible:ring-1 focus-visible:ring-white/20"
              />
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  void handleSearch();
                }}
                disabled={isSearching || !employeeNumber.trim()}
                className="absolute right-3 z-10 flex h-8 items-center justify-center px-2 text-[12px] font-medium text-[#60a5fa] transition-colors hover:text-white disabled:opacity-50"
              >
                {isSearching ? '...' : '검색'}
              </button>
            </div>
          </div>

          {searchedUser && (
            <div className="flex flex-col gap-1 rounded-[4px] border border-[rgba(96,165,250,0.2)] bg-[#0d1c2d] p-[17px]">
              <div className="flex items-center gap-2">
                <span className="font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[14px] text-white">
                  {searchedUser.name}
                </span>
                <div className="rounded-[2px] bg-[rgba(96,165,250,0.1)] px-1.5 py-0.5">
                  <span className="font-['Inter:Regular',sans-serif] text-[10px] text-[#60a5fa]">
                    ID: {searchedUser.employeeNumber}
                  </span>
                </div>
              </div>
              <span className="font-['Inter:Regular',sans-serif] text-[12px] text-[#c1c7d3]">
                {searchedUser.email || 'Email not available in summary'}
              </span>
            </div>
          )}
        </div>

        <DialogFooter className="gap-3 px-8 pt-2 pb-8 sm:justify-end">
          <button
            onClick={onClose}
            className="rounded-[4px] border border-[#414751] px-[25px] py-[11px] font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[14px] text-[#c1c7d3] transition-colors hover:bg-white/5"
          >
            취소
          </button>
          <button
            onClick={handleUpdate}
            disabled={!projectName || !searchedUser || isUpdating}
            className="rounded-[4px] bg-[#3b82f6] px-[24px] py-[10px] font-['WenQuanYi_Zen_Hei:Medium',sans-serif] text-[14px] font-medium text-white shadow-[0px_10px_15px_-3px_rgba(59,130,246,0.2)] transition-colors hover:bg-[#2563eb] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isUpdating ? '저장 중...' : '저장하기'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
