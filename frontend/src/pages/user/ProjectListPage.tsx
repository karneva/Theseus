import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Folder } from 'lucide-react';
import { projectApi } from '@/features/projects/api';
import type { MyProjectResponse } from '@/features/projects/api';

export default function ProjectListPage() {
  const [projects, setProjects] = useState<MyProjectResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        setIsLoading(true);
        // Temporarily fetching page 0, size 20
        const data = await projectApi.getMyProjects(0, 20);
        setProjects(data.content);
      } catch (error) {
        console.error('Failed to fetch projects', error);
      } finally {
        setIsLoading(false);
      }
    };

    void fetchProjects();
  }, []);

  return (
    <div className="relative flex size-full min-h-screen flex-col content-stretch items-center px-[24px] pt-[64px] pb-[100px]">
      {/* Background Decorative Elements */}
      <div className="pointer-events-none absolute right-0 bottom-[-49px] h-[512px] w-[426.66px] rounded-[12px] bg-[rgba(164,201,255,0.05)] blur-[60px]" />
      <div className="pointer-events-none absolute top-[80px] left-0 h-[341.33px] w-[320px] rounded-[12px] bg-[rgba(250,189,52,0.05)] blur-[50px]" />

      <div className="relative z-10 flex w-full max-w-[896px] shrink-0 flex-col content-stretch items-start pb-[32px]">
        <div className="relative flex w-full max-w-[896px] shrink-0 flex-col content-stretch items-center gap-[8px]">
          <div className="relative flex w-full shrink-0 flex-col content-stretch items-center">
            <h1 className="text-[24px] font-medium tracking-[-0.4px] text-[#d4e4fa]">프로젝트</h1>
          </div>
          <div className="relative flex w-full shrink-0 flex-col content-stretch items-center opacity-70">
            <p className="text-center text-[16px] font-medium text-[#c1c7d3]">
              현재 참여 중인 연구 및 시스템 자동화 프로젝트 목록입니다.
            </p>
          </div>
        </div>
      </div>

      <div className="relative z-10 flex w-full max-w-[896px] shrink-0 flex-col content-stretch items-start gap-[16px]">
        {isLoading ? (
          <div className="flex w-full justify-center py-20 text-[#8b919d]">
            프로젝트 정보를 불러오는 중입니다...
          </div>
        ) : projects.length === 0 ? (
          <div className="flex w-full justify-center py-20 text-[#8b919d]">
            참여 중인 프로젝트가 없습니다.
          </div>
        ) : (
          projects.map((project) => (
            <div
              key={project.projectId}
              onClick={() => navigate(`/projects/${project.projectId}`)}
              className="group relative flex w-full shrink-0 cursor-pointer content-stretch items-center justify-between rounded-[8px] border border-[rgba(65,71,81,0.3)] bg-[rgba(30,41,59,0.4)] p-[25px] backdrop-blur-[6px] transition-all hover:border-[rgba(96,165,250,0.5)] hover:bg-[rgba(30,41,59,0.6)]"
            >
              <div className="relative flex-1 shrink-0">
                <div className="relative flex size-full items-center gap-[24px]">
                  <div className="relative flex size-[64px] shrink-0 items-center justify-center rounded-[4px] border border-[rgba(65,71,81,0.2)] bg-[#273647] p-px shadow-[inset_0px_2px_4px_0px_rgba(0,0,0,0.05)] transition-colors group-hover:bg-[#2d3f54]">
                    <Folder className="h-8 w-8 text-[#60a5fa]" />
                  </div>
                  <div className="relative flex min-w-0 flex-1 flex-col items-start gap-[8px]">
                    <div className="relative flex w-full items-center gap-[12px]">
                      <div className="relative flex shrink-0 flex-col items-start">
                        <h3 className="truncate text-[18px] font-medium text-[#d4e4fa]">
                          {project.name}
                        </h3>
                      </div>
                      <div className="relative flex shrink-0 items-center gap-[8px]">
                        <div
                          className={`relative flex shrink-0 flex-col content-stretch items-start rounded-[2px] border px-[9px] py-[3px] ${project.projectStatus === 'ACTIVE' ? 'border-[rgba(164,201,255,0.2)] bg-[rgba(164,201,255,0.1)]' : 'border-[rgba(156,163,175,0.2)] bg-[rgba(156,163,175,0.1)]'}`}
                        >
                          <span
                            className={`text-[10px] leading-[15px] font-normal ${project.projectStatus === 'ACTIVE' ? 'text-[#a4c9ff]' : 'text-gray-400'}`}
                          >
                            {project.projectStatus}
                          </span>
                        </div>
                        <div
                          className={`relative flex shrink-0 flex-col content-stretch items-start rounded-[2px] border px-[9px] py-[3px] ${project.projectRole === 'ADMIN' ? 'border-[rgba(250,189,52,0.2)] bg-[rgba(250,189,52,0.1)]' : 'border-[rgba(52,211,153,0.2)] bg-[rgba(52,211,153,0.1)]'}`}
                        >
                          <span
                            className={`text-[10px] leading-[15px] font-normal ${project.projectRole === 'ADMIN' ? 'text-[#fabd34]' : 'text-[#34d399]'}`}
                          >
                            {project.projectRole}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="flex w-full flex-col items-start pr-4">
                      <p className="line-clamp-2 text-[14px] leading-[22px] font-medium text-[#c1c7d3]">
                        {project.description}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="relative flex shrink-0 flex-col items-end gap-[3px]">
                <span className="text-[12px] leading-[15px] font-medium text-[#8b919d]">
                  최근 업데이트
                </span>
                <span className="font-mono text-[13px] leading-[16.5px] text-[#c1c7d3]">
                  {new Date(project.updatedAt)
                    .toLocaleString('ko-KR', {
                      year: 'numeric',
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                      hour12: false,
                    })
                    .replace(/\. /g, '.')
                    .replace(':', ':')}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
