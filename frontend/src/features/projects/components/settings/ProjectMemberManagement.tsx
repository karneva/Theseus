import { compareProjectMembers } from '../../utils/memberPolicy';
import { useState, useEffect } from 'react';
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
import { Plus, Edit2 } from 'lucide-react';
import { memberApi } from '@/features/projects/api/member';
import type { ProjectMemberResponse } from '@/features/projects/api';
import { AddMemberModal } from './AddMemberModal';
import { EditMemberModal } from './EditMemberModal';

interface ProjectMemberManagementProps {
  projectId: string;
}

export function ProjectMemberManagement({ projectId }: ProjectMemberManagementProps) {
  const [members, setMembers] = useState<ProjectMemberResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchTrigger, setFetchTrigger] = useState(0);

  // States for Add Member Dialog
  const [isAddOpen, setIsAddOpen] = useState(false);

  // States for Edit Member Dialog
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [selectedMember, setSelectedMember] = useState<ProjectMemberResponse | null>(null);

  const refetch = () => setFetchTrigger((n) => n + 1);

  useEffect(() => {
    let cancelled = false;
    const fetchMembers = async () => {
      setIsLoading(true);
      try {
        const res = await memberApi.getMembers(projectId, 0, 100, 'ALL');
        if (cancelled) return;

        setMembers([...(res || [])].sort(compareProjectMembers));
      } catch (err) {
        if (!cancelled) console.error('Failed to fetch members', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void fetchMembers();
    return () => {
      cancelled = true;
    };
  }, [projectId, fetchTrigger]);

  const openEditModal = (member: ProjectMemberResponse) => {
    setSelectedMember(member);
    setIsEditOpen(true);
  };

  return (
    <Card className="overflow-x-auto border-slate-800 bg-slate-900/40 shadow-2xl shadow-blue-500/5 backdrop-blur-xl">
      <CardHeader className="mb-6 flex min-w-[900px] flex-row items-center justify-between border-b border-slate-800/50">
        <div className="min-w-max">
          <CardTitle className="mb-1 font-['Space_Grotesk'] whitespace-nowrap text-white">
            멤버 관리
          </CardTitle>
          <CardDescription className="whitespace-nowrap text-slate-400">
            프로젝트에 참여 중인 멤버와 권한을 관리합니다.
          </CardDescription>
        </div>

        <Button
          className="flex items-center gap-2 bg-blue-400 font-bold text-[#003a6b] hover:bg-blue-500"
          onClick={() => setIsAddOpen(true)}
        >
          <Plus className="h-4 w-4" /> 멤버 추가
        </Button>
        <AddMemberModal
          projectId={projectId}
          isOpen={isAddOpen}
          onOpenChange={setIsAddOpen}
          onSuccess={refetch}
        />
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="animate-pulse py-12 text-center text-slate-500">
            멤버 목록을 불러오는 중...
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/20">
            <Table className="min-w-[900px]">
              <TableHeader className="bg-slate-950/50">
                <TableRow className="border-slate-800 hover:bg-transparent">
                  <TableHead className="w-[180px] text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                    이름 / 사번
                  </TableHead>
                  <TableHead className="w-[160px] text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                    역할 / 레벨
                  </TableHead>
                  <TableHead className="w-[300px] pl-4 text-center text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                    도구 권한
                  </TableHead>
                  <TableHead className="w-[120px] text-center text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                    상태
                  </TableHead>
                  <TableHead className="w-[80px] text-center text-[10px] font-bold tracking-widest text-slate-400 uppercase">
                    관리
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.length === 0 ? (
                  <TableRow className="border-slate-800 hover:bg-slate-900/20">
                    <TableCell colSpan={5} className="py-12 text-center font-medium text-slate-500">
                      등록된 멤버가 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  members.map((member) => (
                    <TableRow
                      key={member.projectMemberId}
                      className="border-slate-800 transition-colors hover:bg-slate-900/40"
                    >
                      <TableCell>
                        <div className="font-bold text-slate-200">{member.name}</div>
                        <div className="mt-0.5 font-mono text-xs text-slate-500">
                          {member.employeeNumber}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className={cn(
                              'flex items-center gap-1.5 border-transparent px-2 py-0.5 font-bold tracking-tight',
                              'border-slate-700/50 bg-slate-800/40 text-slate-300 ring-1 ring-slate-800/50',
                            )}
                          >
                            {member.projectRole}
                          </Badge>
                          <span className="text-[10px] font-bold whitespace-nowrap text-slate-500">
                            LV.{member.accessLevel}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1.5 pl-4">
                          {member.canUseTool && (
                            <Badge
                              variant="outline"
                              className="h-4 border-slate-800 bg-slate-900/50 px-1.5 py-0 text-[10px] font-bold tracking-tight text-slate-400 uppercase"
                            >
                              Use
                            </Badge>
                          )}
                          {member.canCreateTool && (
                            <Badge
                              variant="outline"
                              className="h-4 border-slate-800 bg-slate-900/50 px-1.5 py-0 text-[10px] font-bold tracking-tight text-slate-400 uppercase"
                            >
                              Create
                            </Badge>
                          )}
                          {member.canUpdateTool && (
                            <Badge
                              variant="outline"
                              className="h-4 border-slate-800 bg-slate-900/50 px-1.5 py-0 text-[10px] font-bold tracking-tight text-slate-400 uppercase"
                            >
                              Update
                            </Badge>
                          )}
                          {member.canDeleteTool && (
                            <Badge
                              variant="outline"
                              className="h-4 border-slate-800 bg-slate-900/50 px-1.5 py-0 text-[10px] font-bold tracking-tight text-slate-400 uppercase"
                            >
                              Delete
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant={member.status === 'IN_PROGRESS' ? 'default' : 'secondary'}
                          className={cn(
                            'text-[10px] font-bold',
                            member.status === 'IN_PROGRESS'
                              ? 'bg-blue-400 text-[#003a6b] hover:bg-blue-400'
                              : 'bg-slate-800 text-slate-400 hover:bg-slate-800',
                          )}
                        >
                          {member.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-center">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => openEditModal(member)}
                          className="text-slate-400 hover:bg-blue-400/10 hover:text-blue-400"
                        >
                          <Edit2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      {isEditOpen && selectedMember && (
        <EditMemberModal
          key={selectedMember.projectMemberId}
          projectId={projectId}
          isOpen={isEditOpen}
          onOpenChange={setIsEditOpen}
          onSuccess={refetch}
          selectedMember={selectedMember}
        />
      )}
    </Card>
  );
}
