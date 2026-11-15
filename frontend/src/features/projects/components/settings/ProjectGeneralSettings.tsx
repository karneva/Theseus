import { useState, useEffect } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardFooter,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { projectApi } from '@/features/projects/api';

interface ProjectGeneralSettingsProps {
  projectId: string;
}

export function ProjectGeneralSettings({ projectId }: ProjectGeneralSettingsProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchProjectData = async () => {
      try {
        setIsLoading(true);
        const res = await projectApi.getProject(projectId);
        if (cancelled) return;
        setName(res.name);
        setDescription(res.description || '');
        setIsActive(res.status === 'ACTIVE');
      } catch (err) {
        if (!cancelled) console.error('Failed to load project details', err);
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    void fetchProjectData();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const handleSave = async () => {
    try {
      setIsSaving(true);
      await projectApi.updateProject(projectId, {
        name,
        description,
        status: isActive ? 'ACTIVE' : 'INACTIVE',
      });
      alert('프로젝트 정보가 성공적으로 업데이트되었습니다.');
    } catch (err) {
      console.error('Failed to update project', err);
      alert('업데이트에 실패했습니다.');
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <div className="p-8 text-center">로딩 중...</div>;
  }

  return (
    <Card className="overflow-x-auto border-slate-800 bg-slate-900/40 shadow-2xl shadow-blue-500/5 backdrop-blur-xl">
      <CardHeader className="min-w-[500px]">
        <CardTitle className="font-['Space_Grotesk'] whitespace-nowrap text-white">
          일반 설정
        </CardTitle>
        <CardDescription className="whitespace-nowrap text-slate-400">
          프로젝트의 기본 정보를 수정합니다.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6 overflow-x-auto">
        <div className="min-w-[500px] space-y-6">
          <div className="space-y-2">
            <Label
              htmlFor="projectName"
              className="text-[10px] font-medium tracking-wide text-slate-300 uppercase"
            >
              프로젝트 이름
            </Label>
            <Input
              id="projectName"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="프로젝트 이름을 입력하세요"
              className="border-slate-800 bg-slate-950/50 text-slate-200 placeholder:text-slate-600 focus:border-blue-400/50 focus:ring-blue-400/20"
            />
          </div>

          <div className="space-y-2">
            <Label
              htmlFor="projectDescription"
              className="text-[10px] font-medium tracking-wide text-slate-300 uppercase"
            >
              프로젝트 설명
            </Label>
            <Textarea
              id="projectDescription"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="프로젝트에 대한 설명을 입력하세요"
              rows={4}
              className="border-slate-800 bg-slate-950/50 text-slate-200 placeholder:text-slate-600 focus:border-blue-400/50 focus:ring-blue-400/20"
            />
          </div>

          <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/30 p-4">
            <div className="space-y-0.5">
              <Label className="font-medium text-slate-200">프로젝트 활성화 상태</Label>
            </div>
            <Switch
              checked={isActive}
              onCheckedChange={setIsActive}
              className="data-[state=checked]:bg-blue-400"
            />
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex min-w-[500px] justify-end border-t border-slate-800 p-6">
        <Button
          onClick={handleSave}
          disabled={isSaving}
          className="bg-blue-400 px-8 font-bold text-[#003a6b] hover:bg-blue-500"
        >
          {isSaving ? '저장 중...' : '변경사항 저장'}
        </Button>
      </CardFooter>
    </Card>
  );
}
