import express from 'express';
import { renderPage } from '../libraries/middleware.js';
import { getDataDir } from '../libraries/data-dir.js';

const router = express.Router();

router.get('/', (req, res) => {
  renderPage(req, res, 'index', {
    title: 'Home',
    activePage: 'home',
    dataDir: getDataDir(),
  });
});

export default router;
