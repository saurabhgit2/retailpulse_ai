import { Navigate, Route, Routes } from 'react-router';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { PublicOnlyRoute } from './components/auth/PublicOnlyRoute';
import { AppShell } from './components/layout/AppShell';
import { PLANNED_PAGES } from './content/plannedPages';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DatasetsPage } from './pages/DatasetsPage';
import { UploadWizardPage } from './pages/UploadWizardPage';
import { DataQualityPage } from './pages/DataQualityPage';
import { ComingSoonPage } from './pages/ComingSoonPage';
import { NotFoundPage } from './pages/NotFoundPage';

/**
 * Every URL in the app and the page it shows. Routes nested inside the
 * <AppShell> route render in its <Outlet />, so they all share the sidebar and
 * top bar, and all of them require a signed-in user.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnlyRoute><LoginPage /></PublicOnlyRoute>} />
      <Route path="/register" element={<PublicOnlyRoute><RegisterPage /></PublicOnlyRoute>} />

      <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
        <Route index element={<Navigate to="/datasets" replace />} />
        <Route path="datasets" element={<DatasetsPage />} />
        <Route path="upload" element={<UploadWizardPage />} />
        <Route path="datasets/:datasetId/quality" element={<DataQualityPage />} />
        {PLANNED_PAGES.map((page) => (
          <Route key={page.path} path={`datasets/:datasetId/${page.path}`} element={<ComingSoonPage page={page} />} />
        ))}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
