import UserManagementSection from '../../features/admin/components/UserManagementSection';
import ProjectListSection from '../../features/admin/components/ProjectListSection';

export default function SuperAdminPage() {
  return (
    <div className="grid h-[calc(100vh-12rem)] min-h-[600px] w-full grid-cols-2 gap-[32px]">
      {/* Left Column: User Management */}
      <UserManagementSection />

      {/* Right Column: Project List */}
      <ProjectListSection />
    </div>
  );
}
