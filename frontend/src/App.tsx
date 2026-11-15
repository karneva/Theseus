import { RouterProvider } from 'react-router-dom';
import { Toaster } from 'sonner';
import { router } from './routes';
import { useAuthBootstrap } from './hooks/useAuthBootstrap';

function App() {
  const authReady = useAuthBootstrap();

  return (
    <>
      {authReady ? (
        <RouterProvider router={router} />
      ) : (
        <div className="min-h-screen bg-[#010f1f]" aria-busy="true" />
      )}
      <Toaster
        theme="dark"
        position="top-right"
        toastOptions={{
          style: {
            background: '#1e293b',
            border: '1px solid #334155',
            color: '#f1f5f9',
          },
        }}
      />
    </>
  );
}

export default App;
