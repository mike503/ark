import { renderPage as tablerockRenderPage } from '@tablerock/standard/middleware';
import './tablerock.js';

export async function renderPage(req, res, pageName, data = {}) {
  return tablerockRenderPage(req, res, pageName, data);
}

export {
  eta,
  adminCheck,
  requireAdmin,
  requireAdminPage,
} from '@tablerock/standard/middleware';
