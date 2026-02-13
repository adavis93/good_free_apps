/* ===========================================
   GOOD FREE APPS — SHARED ANALYTICS
   Version: 1.0.0
   
   Include this script in every app to track
   usage data for the admin dashboard. All
   tracking is anonymous — no personal data
   is collected.
   
   Usage:
     <script src="../../shared/analytics.js"></script>
     
     trackPageView('app-name');
     trackEvent('action', 'app-name', { key: 'value' });
   =========================================== */

(function () {
  'use strict';

  // =========================================
  // CONFIGURATION
  // =========================================
  const CONFIG = {
    // Set this to your Cloudflare Worker URL (or other backend)
    ENDPOINT: 'https://good-free-apps-api.alexanderdavis0293.workers.dev',  // e.g. 'https://your-worker.workers.dev/api/track'

    // Set to true once your backend is ready
    ENABLED: true,

    // Batch events and send periodically (ms)
    BATCH_INTERVAL: 5000,

    // Max events to queue before force-sending
    BATCH_SIZE: 10,

    // Session timeout (30 min of inactivity)
    SESSION_TIMEOUT: 30 * 60 * 1000,

    // Debug mode — logs events to console
    DEBUG: true,
  };

  // =========================================
  // EVENT QUEUE
  // =========================================
  let eventQueue = [];
  let sessionId = null;
  let sessionStart = null;
  let lastActivity = null;
  let batchTimer = null;

  // =========================================
  // SESSION MANAGEMENT
  // =========================================
  function getOrCreateSession() {
    const now = Date.now();

    // Check if existing session is still valid
    if (sessionId && lastActivity && (now - lastActivity < CONFIG.SESSION_TIMEOUT)) {
      lastActivity = now;
      return sessionId;
    }

    // Create new session (anonymous random ID)
    sessionId = 'sess_' + Math.random().toString(36).substring(2, 15);
    sessionStart = now;
    lastActivity = now;
    return sessionId;
  }

  // =========================================
  // CORE TRACKING FUNCTIONS
  // =========================================

  /**
   * Track a page view.
   * Call this once when the app loads.
   * @param {string} appName - The app identifier (e.g. 'calculator')
   */
  function trackPageView(appName) {
    queueEvent({
      type: 'page_view',
      app: appName,
      path: window.location.pathname,
      referrer: document.referrer || null,
    });
  }

  /**
   * Track a custom event.
   * Call this for important user actions.
   * @param {string} action - The action name (e.g. 'calculation_done')
   * @param {string} appName - The app identifier
   * @param {Object} [metadata] - Optional additional data
   */
  function trackEvent(action, appName, metadata) {
    queueEvent({
      type: 'event',
      app: appName,
      action: action,
      metadata: metadata || null,
    });
  }

  /**
   * Track session start.
   * Call this once when the app loads.
   * @param {string} appName - The app identifier
   */
  function trackSessionStart(appName) {
    queueEvent({
      type: 'session_start',
      app: appName,
    });
  }

  /**
   * Set up automatic error tracking.
   * Call this once when the app loads.
   * @param {string} appName - The app identifier
   */
  function setupErrorTracking(appName) {
    window.addEventListener('error', function (e) {
      queueEvent({
        type: 'error',
        app: appName,
        action: 'js_error',
        metadata: {
          message: e.message,
          source: e.filename,
          line: e.lineno,
          col: e.colno,
        },
      });
    });

    window.addEventListener('unhandledrejection', function (e) {
      queueEvent({
        type: 'error',
        app: appName,
        action: 'unhandled_rejection',
        metadata: {
          message: e.reason ? e.reason.toString() : 'Unknown',
        },
      });
    });
  }

  // =========================================
  // EVENT QUEUE & BATCHING
  // =========================================
  function queueEvent(event) {
    const session = getOrCreateSession();

    const enrichedEvent = Object.assign({}, event, {
      session_id: session,
      timestamp: new Date().toISOString(),
      user_agent: navigator.userAgent,
      screen: window.innerWidth + 'x' + window.innerHeight,
    });

    if (CONFIG.DEBUG) {
      console.log('[Analytics]', enrichedEvent);
    }

    if (!CONFIG.ENABLED || !CONFIG.ENDPOINT) {
      return; // Silently skip if not configured
    }

    eventQueue.push(enrichedEvent);

    // Force flush if queue is full
    if (eventQueue.length >= CONFIG.BATCH_SIZE) {
      flushEvents();
    }

    // Start batch timer if not running
    if (!batchTimer) {
      batchTimer = setTimeout(flushEvents, CONFIG.BATCH_INTERVAL);
    }
  }

  function flushEvents() {
    if (batchTimer) {
      clearTimeout(batchTimer);
      batchTimer = null;
    }

    if (eventQueue.length === 0) return;

    const eventsToSend = eventQueue.slice();
    eventQueue = [];

    // Use sendBeacon for reliability (works even on page close)
    if (navigator.sendBeacon) {
      const blob = new Blob(
        [JSON.stringify({ events: eventsToSend })],
        { type: 'application/json' }
      );
      navigator.sendBeacon(CONFIG.ENDPOINT, blob);
    } else {
      // Fallback to fetch
      fetch(CONFIG.ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: eventsToSend }),
        keepalive: true,
      }).catch(function () {
        // Silently fail — analytics should never break the app
      });
    }
  }

  // Flush on page unload
  window.addEventListener('beforeunload', flushEvents);

  // Flush on visibility change (tab hidden)
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      flushEvents();
    }
  });

  // =========================================
  // EXPOSE PUBLIC API
  // =========================================
  window.trackPageView = trackPageView;
  window.trackEvent = trackEvent;
  window.trackSessionStart = trackSessionStart;
  window.setupErrorTracking = setupErrorTracking;
})();
