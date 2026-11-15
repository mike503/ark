import express from 'express';
import passport from 'passport';
import { renderPage } from '../libraries/middleware.js';
import { writeLog } from '../libraries/common.js';

const router = express.Router();

router.get('/login', (req, res) => {
  if (req.isAuthenticated()) {
    return res.redirect('/');
  }

  const error = req.query.error || null;
  renderPage(req, res, 'login', {
    title: 'Login',
    activePage: 'login',
    error,
    isLoginPage: true,
  });
});

router.post('/login', (req, res, next) => {
  writeLog('DEBUG', 'Login POST received for:', req.body.email);

  passport.authenticate('local', (err, user, info) => {
    if (err) {
      writeLog('DEBUG', 'Authentication error:', err);
      return res.redirect('/login?error=Authentication+error');
    }

    if (!user) {
      writeLog('DEBUG', 'Authentication failed:', info?.message);
      return res.redirect('/login?error=Invalid+email+or+password');
    }

    req.logIn(user, (err) => {
      if (err) {
        writeLog('DEBUG', 'Login session error:', err);
        return res.redirect('/login?error=Session+error');
      }

      const returnTo = req.session.returnTo || '/';
      delete req.session.returnTo;

      req.session.save((err) => {
        if (err) {
          writeLog('DEBUG', 'Session save error:', err);
        }
        res.redirect(returnTo);
      });
    });
  })(req, res, next);
});

router.get('/logout', (req, res) => {
  req.logout((err) => {
    if (err) {
      writeLog('DEBUG', 'Logout error:', err);
      return res.status(500).send('Logout error');
    }

    req.session.destroy(() => {
      res.clearCookie('connect.sid');
      res.redirect('/login');
    });
  });
});

router.get('/api/user', (req, res) => {
  if (!req.isAuthenticated()) {
    return res.status(401).json({ authenticated: false, loginUrl: '/login' });
  }

  res.json({
    authenticated: true,
    user: {
      user_id: req.user.user_id,
      email: req.user.email,
      first_name: req.user.first_name,
      last_name: req.user.last_name,
      user_level: req.user.user_level,
    },
  });
});

export default router;
