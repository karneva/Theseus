import { useState } from 'react';
import { adminApi } from '../api';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface AddUserModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function AddUserModal({ isOpen, onClose, onSuccess }: AddUserModalProps) {
  const [newUserForm, setNewUserForm] = useState({
    employeeNumber: '',
    name: '',
    email: '',
    password: '',
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (
      !newUserForm.employeeNumber ||
      !newUserForm.name ||
      !newUserForm.email ||
      !newUserForm.password
    ) {
      alert('모든 필드를 입력해주세요.');
      return;
    }

    setIsSubmitting(true);
    try {
      await adminApi.createUser({
        employeeNumber: newUserForm.employeeNumber,
        name: newUserForm.name,
        email: newUserForm.email,
        password: newUserForm.password,
      });
      setNewUserForm({ employeeNumber: '', name: '', email: '', password: '' });
      onSuccess();
      onClose();
    } catch (error) {
      console.error('Failed to create user:', error);
      alert('사용자 생성에 실패했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="border-[rgba(65,71,81,0.3)] bg-[#051424] text-white sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle className="text-lg font-semibold text-[#d4e4fa]">새 사용자 추가</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="employeeNumber" className="text-right text-sm text-[#a4c9ff]">
              사번
            </Label>
            <Input
              id="employeeNumber"
              value={newUserForm.employeeNumber}
              onChange={(e) => setNewUserForm({ ...newUserForm, employeeNumber: e.target.value })}
              className="col-span-3 border-[rgba(65,71,81,0.3)] bg-[#010f1f] text-[#d4e4fa] focus-visible:ring-1 focus-visible:ring-white/20"
              placeholder="ex) 0000000"
            />
          </div>
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="name" className="text-right text-sm text-[#a4c9ff]">
              이름
            </Label>
            <Input
              id="name"
              value={newUserForm.name}
              onChange={(e) => setNewUserForm({ ...newUserForm, name: e.target.value })}
              className="col-span-3 border-[rgba(65,71,81,0.3)] bg-[#010f1f] text-[#d4e4fa] focus-visible:ring-1 focus-visible:ring-white/20"
              placeholder="ex) 홍길동"
            />
          </div>
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="email" className="text-right text-sm text-[#a4c9ff]">
              이메일
            </Label>
            <Input
              id="email"
              type="email"
              value={newUserForm.email}
              onChange={(e) => setNewUserForm({ ...newUserForm, email: e.target.value })}
              className="col-span-3 border-[rgba(65,71,81,0.3)] bg-[#010f1f] text-[#d4e4fa] focus-visible:ring-1 focus-visible:ring-white/20"
              placeholder="ex) user@example.com"
            />
          </div>
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="password" className="text-right text-sm text-[#a4c9ff]">
              비밀번호
            </Label>
            <Input
              id="password"
              type="password"
              value={newUserForm.password}
              onChange={(e) => setNewUserForm({ ...newUserForm, password: e.target.value })}
              className="col-span-3 border-[rgba(65,71,81,0.3)] bg-[#010f1f] text-[#d4e4fa] focus-visible:ring-1 focus-visible:ring-white/20"
              placeholder="비밀번호를 입력하세요"
            />
          </div>
        </div>
        <DialogFooter>
          <button
            onClick={onClose}
            className="rounded-md border border-[rgba(65,71,81,0.3)] bg-transparent px-4 py-2 text-sm font-medium text-[#c1c7d3] transition-colors hover:bg-white/5"
          >
            취소
          </button>
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="rounded-md bg-[#3b82f6] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[#2563eb] disabled:opacity-50"
          >
            {isSubmitting ? '추가 중...' : '사용자 추가'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
