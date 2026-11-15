import { useState, useEffect } from 'react';
import { Search, MoreVertical, Edit, Layers, Settings2, Plus, Trash2 } from 'lucide-react';
import { adminApi } from '../api';
import type { ProjectSummaryResponse } from '../api';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { StatusBadge } from '@/components/StatusBadge';
import { Pagination } from '@/components/Pagination';
import AddProjectModal from './AddProjectModal';
import EditProjectModal from './EditProjectModal';

export default function ProjectListSection() {
  const [projects, setProjects] = useState<ProjectSummaryResponse[]>([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [selectedProject, setSelectedProject] = useState<ProjectSummaryResponse | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [page, setPage] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [totalElements, setTotalElements] = useState(0);
  const [fetchTrigger, setFetchTrigger] = useState(0);

  const refetch = () => setFetchTrigger((n) => n + 1);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      try {
        const data = await adminApi.getProjects(page, 8);
        if (cancelled) return;
        if (data && data.content) {
          setProjects(data.content);
          setTotalPages(data.totalPages);
          setTotalElements(data.totalElements);
        } else {
          setProjects([]);
          setTotalPages(0);
          setTotalElements(0);
        }
      } catch (error) {
        if (!cancelled) {
          console.error('Failed to fetch projects:', error);
          setProjects([]);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [page, fetchTrigger]);

  const handleStatusToggle = async (projectId: number, currentStatus: 'ACTIVE' | 'INACTIVE') => {
    const newStatus = currentStatus === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE';
    try {
      await adminApi.updateProject(projectId, { status: newStatus });
      refetch();
    } catch (error) {
      console.error('Failed to update project status:', error);
      alert('프로젝트 상태 변경에 실패했습니다.');
    }
  };

  const filteredProjects = projects.filter((project) => {
    const searchLower = searchTerm.toLowerCase();
    return (
      project.name.toLowerCase().includes(searchLower) ||
      project.projectAdminName.toLowerCase().includes(searchLower) ||
      project.projectAdminEmployeeNumber.includes(searchTerm)
    );
  });

  return (
    <div className="flex flex-col rounded-lg border border-[rgba(65,71,81,0.3)] bg-[#0d1c2d] shadow-2xl">
      <div className="flex shrink-0 items-center justify-between border-b border-[rgba(65,71,81,0.2)] px-6 pt-6 pb-[25px]">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-[rgba(250,189,52,0.1)]">
            <Layers className="h-5 w-5 text-[#fabd34]" />
          </div>
          <div className="flex flex-col">
            <h3 className="text-[18px] font-medium text-[#d4e4fa]">프로젝트 목록</h3>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute top-1/2 left-3 h-3.5 w-3.5 -translate-y-1/2 text-[#6b7280]" />
            <Input
              value={searchTerm}
              onChange={(e) => {
                setSearchTerm(e.target.value);
                setPage(0);
              }}
              placeholder="프로젝트 검색..."
              className="h-8 w-[192px] rounded border-[rgba(65,71,81,0.2)] bg-[#010f1f] pl-9 text-[12px] text-[#6b7280] placeholder:text-[#6b7280] focus-visible:ring-1 focus-visible:ring-white/20"
            />
          </div>
          {isEditing && (
            <button
              onClick={() => setIsAddModalOpen(true)}
              className="flex h-8 items-center gap-2 rounded border border-[#a4c9ff]/20 bg-[#1a2c42] px-4 py-1.5 transition-colors hover:bg-[#233852]"
            >
              <Plus className="h-3.5 w-3.5 text-[#a4c9ff]" />
              <span className="text-[14px] font-medium text-[#a4c9ff]">추가</span>
            </button>
          )}
          <button
            onClick={() => setIsEditing(!isEditing)}
            className={`flex h-8 items-center gap-2 rounded px-4 py-1.5 transition-colors ${isEditing ? 'bg-[#fabd34] hover:bg-[#e5ac2d]' : 'bg-[#273647] hover:bg-[#34485e]'}`}
          >
            <Settings2
              className={`h-3.5 w-3.5 ${isEditing ? 'text-[#003a6b]' : 'text-[#fabd34]'}`}
            />
            <span
              className={`text-[14px] font-medium ${isEditing ? 'text-[#003a6b]' : 'text-[#fabd34]'}`}
            >
              {isEditing ? '완료' : '편집'}
            </span>
          </button>
        </div>
      </div>

      <div className="min-h-[500px] w-full">
        <Table className="table-fixed">
          <TableHeader className="sticky top-0 z-10 border-b border-[rgba(65,71,81,0.1)] bg-[rgba(28,43,60,0.5)]">
            <TableRow className="border-none hover:bg-transparent">
              <TableHead className="h-[40px] w-[180px] px-6 py-[10px] text-[14px] font-medium tracking-[1.2px] text-[#c1c7d3] uppercase">
                프로젝트 명
              </TableHead>
              <TableHead className="h-[40px] w-[140px] px-6 py-[10px] text-[14px] font-medium tracking-[1.2px] text-[#c1c7d3] uppercase">
                담당자 사번
              </TableHead>
              <TableHead className="h-[40px] w-[150px] px-6 py-[10px] text-[14px] font-medium tracking-[1.2px] text-[#c1c7d3] uppercase">
                담당자 이름
              </TableHead>
              <TableHead className="h-[40px] w-[80px] px-6 py-[10px] text-center text-[14px] font-medium tracking-[1.2px] text-[#c1c7d3] uppercase">
                상태
              </TableHead>
              <TableHead className="h-10 w-[83px] px-6 py-2 text-right font-medium text-white/60"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredProjects.length === 0
              ? !isLoading && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-white/40">
                      프로젝트가 없습니다.
                    </TableCell>
                  </TableRow>
                )
              : filteredProjects.map((project) => (
                  <TableRow
                    key={project.projectId}
                    className="h-[57px] border-t border-[rgba(65,71,81,0.1)]"
                  >
                    <TableCell className="truncate px-6 py-[10px] text-[14px] font-medium whitespace-nowrap text-[#d4e4fa]">
                      {project.name}
                    </TableCell>
                    <TableCell className="truncate px-6 py-[10px] font-mono text-[15px] whitespace-nowrap text-[#a4c9ff]">
                      {project.projectAdminEmployeeNumber}
                    </TableCell>
                    <TableCell className="truncate px-6 py-[10px] text-[15px] font-medium whitespace-nowrap text-[#c1c7d3]">
                      {project.projectAdminName}
                    </TableCell>
                    <TableCell className="px-6 py-[10px] text-center">
                      <StatusBadge status={project.status} />
                    </TableCell>
                    <TableCell className="px-6 py-3 text-center">
                      {isEditing && (
                        <div className="flex items-center justify-center gap-1">
                          <DropdownMenu>
                            <DropdownMenuTrigger className="rounded-md p-2 text-white/60 transition-colors outline-none hover:bg-white/10">
                              <MoreVertical className="h-4 w-4" />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              className="min-w-[150px] border-white/10 bg-[#051424] text-white"
                            >
                              <DropdownMenuItem
                                className="cursor-pointer gap-2 hover:bg-white/10 focus:bg-white/10"
                                onClick={() => {
                                  setSelectedProject(project);
                                  setIsEditModalOpen(true);
                                }}
                              >
                                <Edit className="h-4 w-4" />
                                <span>프로젝트 수정</span>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                          <button
                            onClick={() => handleStatusToggle(project.projectId, project.status)}
                            className="rounded-md p-2 text-red-400/60 transition-colors hover:bg-red-500/10 hover:text-red-400"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
            {!isLoading &&
              filteredProjects.length > 0 &&
              filteredProjects.length < 8 &&
              Array.from({ length: 8 - filteredProjects.length }).map((_, index) => (
                <TableRow
                  key={`empty-${index}`}
                  className="h-[57px] border-t border-[rgba(65,71,81,0.05)] hover:bg-transparent"
                >
                  <TableCell colSpan={5} />
                </TableRow>
              ))}
          </TableBody>
        </Table>
      </div>

      {/* Footer / Pagination */}
      <Pagination
        page={page}
        totalPages={totalPages}
        totalElements={totalElements}
        onPageChange={setPage}
        itemName="projects"
      />

      <AddProjectModal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        onSuccess={refetch}
      />

      <EditProjectModal
        isOpen={isEditModalOpen}
        onClose={() => {
          setIsEditModalOpen(false);
          setSelectedProject(null);
        }}
        onSuccess={refetch}
        project={selectedProject}
        key={selectedProject?.projectId ?? 0}
      />
    </div>
  );
}
