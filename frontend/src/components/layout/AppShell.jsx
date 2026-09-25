import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router';
import { DatasetProvider } from '../../context/DatasetProvider';
import { USE_MOCK_API } from '../../utils/constants';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { MockModeBanner } from './MockModeBanner';

/**
 * The frame around every signed-in page: sidebar, top bar and content area.
 * <Outlet /> is where React Router renders the page for the current URL.
 */
export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  // Close the mobile menu whenever the page changes.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <DatasetProvider>
      <div className="min-h-screen lg:grid lg:grid-cols-[15.5rem_minmax(0,1fr)]">
        {/* Desktop sidebar */}
        <aside className="hidden border-r border-rule bg-surface lg:block">
          <div className="sticky top-0 h-screen">
            <Sidebar />
          </div>
        </aside>

        {/* Mobile sidebar: an overlay drawer */}
        {menuOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <button
              type="button"
              className="absolute inset-0 h-full w-full bg-black/40"
              aria-label="Close navigation"
              onClick={() => setMenuOpen(false)}
            />
            <div className="relative h-full w-64 border-r border-rule bg-surface">
              <Sidebar onNavigate={() => setMenuOpen(false)} />
            </div>
          </div>
        )}

        <div className="flex min-w-0 flex-col">
          {USE_MOCK_API && <MockModeBanner />}
          <TopBar onOpenMenu={() => setMenuOpen(true)} />
          <main id="main" className="flex-1 px-4 py-6 sm:px-8 sm:py-8">
            <div className="mx-auto w-full max-w-6xl">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </DatasetProvider>
  );
}
