import { Outlet } from 'react-router-dom';

export default function AuthLayout() {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center overflow-hidden bg-[#051424]">
      {/* Main content container */}
      <div className="relative z-10 flex w-full justify-center p-4">
        <Outlet />
      </div>
    </div>
  );
}
