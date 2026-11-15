#!/usr/bin/env node

import express from 'express';
import session from 'express-session';
import mysqlSessionFactory from 'express-mysql-session';
import passport from 'passport';
import cookieParser from 'cookie-parser';
import { Eta } from 'eta';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { pool } from './libraries/db.js';
import { getLocalStrategy, serializeUser, deserializeUser, autheliaMiddleware } from './libraries/auth.js';
import { writeLog } from './libraries/common.js';
import { ensureDataDirs, getDataDir } from './libraries/data-dir.js';
import authRouter from './routes/auth.js';
import apiRouter from './routes/api.js';
import pagesRouter from './routes/pages.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const port = parseInt(process.env.APP_PORT || '3010', 10);

app.set('trust proxy', 1);

const eta = new Eta({
  views: join(__dirname, 'views'),
  cache: process.env.NODE_ENV === 'production',
  autoEscape: false,
});
app.engine('eta', eta.render.bind(eta));
app.set('view engine', 'eta');
app.set('views', join(__dirname, 'views'));

app.use('/js', express.static(join(__dirname, 'public/js')));
app.use('/css', express.static(join(__dirname, 'public/css')));
app.use('/vendor', express.static(join(__dirname, 'public/vendor')));

const MySQLStore = mysqlSessionFactory(session);
const sessionStore = new MySQLStore({
  clearExpired: true,
  checkExpirationInterval: 900000,
  expiration: 30 * 24 * 60 * 60 * 1000,
  createDatabaseTable: true,
  schema: {
    tableName: 'sessions',
    columnNames: {
      session_id: 'session_id',
      expires: 'expires',
      data: 'data',
    },
  },
}, pool);

app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(cookieParser());

app.use(session({
  store: sessionStore,
  secret: process.env.SESSION_SECRET || 'ark-secret-change-me',
  resave: false,
  saveUninitialized: false,
  cookie: {
    maxAge: 30 * 24 * 60 * 60 * 1000,
    httpOnly: true,
    secure: 'auto',
    sameSite: 'lax',
    path: '/',
  },
}));

app.use(passport.initialize());
app.use(passport.session());
app.use(autheliaMiddleware);

passport.use(getLocalStrategy());
passport.serializeUser(serializeUser);
passport.deserializeUser(deserializeUser);

function isApiPath(path) {
  return path.startsWith('/api/');
}

app.use((req, res, next) => {
  const publicRoutes = ['/login', '/logout', '/api/health'];
  const isPublicRoute = publicRoutes.some((route) => req.path === route);
  const isAgentApi = req.path.startsWith('/api/agent/');
  const isStaticFile = req.path.startsWith('/css/') ||
    req.path.startsWith('/js/') ||
    req.path.startsWith('/vendor/');

  if (isPublicRoute || isStaticFile || isAgentApi) {
    return next();
  }

  if (!req.isAuthenticated()) {
    if (isApiPath(req.path)) {
      return res.status(401).json({ error: 'Authentication required', loginUrl: '/login' });
    }
    req.session.returnTo = req.originalUrl || req.url;
    return res.redirect('/login');
  }

  next();
});

app.use(authRouter);
app.use(apiRouter);
app.use(pagesRouter);

app.use('/api/*', (req, res) => {
  res.status(404).json({ error: 'API endpoint not found' });
});

app.use((req, res) => {
  if (isApiPath(req.path)) {
    return res.status(404).json({ error: 'API endpoint not found' });
  }
  res.status(404).send('Page not found');
});

await ensureDataDirs();

app.listen(port, () => {
  writeLog('INFO', `ark listening on port ${port}`);
  writeLog('INFO', `Health check: http://localhost:${port}/api/health`);
  writeLog('INFO', `Data dir: ${getDataDir()}`);
});
