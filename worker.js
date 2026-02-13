/* ===========================================
   GOOD FREE APPS — CLOUDFLARE WORKER
   Analytics & Feedback API
   =========================================== */

// CORS headers for all responses
const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
};

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    const url = new URL(request.url);
    const path = url.pathname;

    try {
      // Route: POST /api/track - Receive analytics events
      if (path === '/api/track' && request.method === 'POST') {
        return await handleTrackEvents(request, env);
      }

      // Route: POST /api/feedback - Receive feedback submissions
      if (path === '/api/feedback' && request.method === 'POST') {
        return await handleFeedback(request, env);
      }

      // Route: GET /api/dashboard - Get admin dashboard data
      if (path === '/api/dashboard' && request.method === 'GET') {
        return await handleDashboard(request, env);
      }

      // 404 for unknown routes
      return jsonResponse({ error: 'Not found' }, 404);

    } catch (error) {
      console.error('Worker error:', error);
      return jsonResponse({ error: 'Internal server error' }, 500);
    }
  }
};

/* ===========================================
   ANALYTICS TRACKING
   =========================================== */
async function handleTrackEvents(request, env) {
  try {
    const body = await request.json();
    const events = body.events || [];

    if (!Array.isArray(events) || events.length === 0) {
      return jsonResponse({ error: 'Invalid events array' }, 400);
    }

    // Process each event
    const timestamp = Date.now();
    const today = getDateKey(new Date());

    for (const event of events) {
      // Store event in KV (key pattern: events:{date}:{timestamp}:{random})
      const eventKey = `events:${today}:${timestamp}:${randomId()}`;
      await env.ANALYTICS_KV.put(eventKey, JSON.stringify(event), {
        expirationTtl: 31536000, // 1 year (we can adjust retention later)
      });

      // Update daily aggregates
      await updateDailyStats(env, event, today);

      // Track errors separately for easy retrieval
      if (event.type === 'error') {
        const errorKey = `errors:${today}:${timestamp}:${randomId()}`;
        await env.ANALYTICS_KV.put(errorKey, JSON.stringify(event), {
          expirationTtl: 7776000, // 90 days for errors
        });
      }
    }

    return jsonResponse({ success: true, count: events.length });

  } catch (error) {
    console.error('Track events error:', error);
    return jsonResponse({ error: 'Failed to process events' }, 500);
  }
}

/* ===========================================
   FEEDBACK HANDLING
   =========================================== */
async function handleFeedback(request, env) {
  try {
    const feedback = await request.json();

    // Validate required fields
    if (!feedback.text || feedback.text.trim().length === 0) {
      return jsonResponse({ error: 'Feedback text is required' }, 400);
    }

    // Add timestamp and ID
    feedback.id = randomId();
    feedback.timestamp = new Date().toISOString();

    // Store feedback (key pattern: feedback:{timestamp}:{id})
    const feedbackKey = `feedback:${Date.now()}:${feedback.id}`;
    await env.ANALYTICS_KV.put(feedbackKey, JSON.stringify(feedback));

    // Update feedback count in daily stats
    const today = getDateKey(new Date());
    await incrementStat(env, `stats:${today}:feedback_count`, 1);

    return jsonResponse({ success: true, id: feedback.id });

  } catch (error) {
    console.error('Feedback error:', error);
    return jsonResponse({ error: 'Failed to save feedback' }, 500);
  }
}

/* ===========================================
   ADMIN DASHBOARD DATA
   =========================================== */
async function handleDashboard(request, env) {
  try {
    // Verify admin authorization
    const authHeader = request.headers.get('Authorization');
    const expectedToken = env.ADMIN_TOKEN || 'admin'; // Falls back to 'admin' if not set

    if (!authHeader || authHeader !== `Bearer ${expectedToken}`) {
      return jsonResponse({ error: 'Unauthorized' }, 401);
    }

    // Get date range (last 30 days)
    const today = new Date();
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    // Fetch overview stats
    const overview = await getOverviewStats(env, thirtyDaysAgo, today);

    // Fetch per-app performance
    const apps = await getAppPerformance(env, thirtyDaysAgo, today);

    // Fetch recent feedback
    const feedback = await getRecentFeedback(env, 50);

    return jsonResponse({
      overview,
      apps,
      feedback,
    });

  } catch (error) {
    console.error('Dashboard error:', error);
    return jsonResponse({ error: 'Failed to load dashboard data' }, 500);
  }
}

/* ===========================================
   STATS AGGREGATION
   =========================================== */
async function updateDailyStats(env, event, dateKey) {
  const statsPrefix = `stats:${dateKey}`;

  // Increment page views
  if (event.type === 'page_view') {
    await incrementStat(env, `${statsPrefix}:page_views`, 1);
    await incrementStat(env, `${statsPrefix}:app:${event.app}:views`, 1);
  }

  // Track unique sessions
  if (event.type === 'session_start') {
    await incrementStat(env, `${statsPrefix}:sessions`, 1);
    await incrementStat(env, `${statsPrefix}:app:${event.app}:sessions`, 1);
  }

  // Track errors
  if (event.type === 'error') {
    await incrementStat(env, `${statsPrefix}:app:${event.app}:errors`, 1);
  }

  // Track custom events
  if (event.type === 'event') {
    await incrementStat(env, `${statsPrefix}:events`, 1);
  }
}

async function incrementStat(env, key, increment) {
  try {
    const current = await env.ANALYTICS_KV.get(key);
    const newValue = (parseInt(current) || 0) + increment;
    await env.ANALYTICS_KV.put(key, newValue.toString(), {
      expirationTtl: 31536000, // 1 year
    });
  } catch (error) {
    console.error('Increment stat error:', error);
  }
}

/* ===========================================
   DATA RETRIEVAL FOR DASHBOARD
   =========================================== */
async function getOverviewStats(env, startDate, endDate) {
  let totalViews = 0;
  let totalSessions = 0;
  let feedbackCount = 0;
  let activeApps = new Set();

  // Iterate through dates
  const currentDate = new Date(startDate);
  while (currentDate <= endDate) {
    const dateKey = getDateKey(currentDate);
    const statsPrefix = `stats:${dateKey}`;

    // Get daily totals
    const views = await env.ANALYTICS_KV.get(`${statsPrefix}:page_views`);
    const sessions = await env.ANALYTICS_KV.get(`${statsPrefix}:sessions`);
    const feedback = await env.ANALYTICS_KV.get(`${statsPrefix}:feedback_count`);

    totalViews += parseInt(views) || 0;
    totalSessions += parseInt(sessions) || 0;
    feedbackCount += parseInt(feedback) || 0;

    // Move to next day
    currentDate.setDate(currentDate.getDate() + 1);
  }

  // Count active apps (apps with at least 1 view)
  const list = await env.ANALYTICS_KV.list({ prefix: 'stats:' });
  for (const key of list.keys) {
    const match = key.name.match(/stats:\d{4}-\d{2}-\d{2}:app:([^:]+):views/);
    if (match) {
      activeApps.add(match[1]);
    }
  }

  return {
    totalViews,
    totalSessions,
    activeApps: activeApps.size,
    feedbackCount,
    viewsTrend: { label: '+0%', direction: 'neutral' },
    sessionsTrend: { label: '+0%', direction: 'neutral' },
    feedbackTrend: { label: '+0%', direction: 'neutral' },
  };
}

async function getAppPerformance(env, startDate, endDate) {
  const appStats = {};

  // Iterate through dates
  const currentDate = new Date(startDate);
  while (currentDate <= endDate) {
    const dateKey = getDateKey(currentDate);
    const statsPrefix = `stats:${dateKey}`;

    // List all app stats for this day
    const list = await env.ANALYTICS_KV.list({ prefix: `${statsPrefix}:app:` });

    for (const key of list.keys) {
      // Parse key: stats:2026-02-12:app:calculator:views
      const match = key.name.match(/app:([^:]+):([^:]+)$/);
      if (!match) continue;

      const [, appName, metric] = match;

      if (!appStats[appName]) {
        appStats[appName] = {
          name: appName,
          icon: '📱', // Default icon
          views: 0,
          sessions: 0,
          errors: 0,
        };
      }

      const value = await env.ANALYTICS_KV.get(key.name);
      const numValue = parseInt(value) || 0;

      if (metric === 'views') appStats[appName].views += numValue;
      if (metric === 'sessions') appStats[appName].sessions += numValue;
      if (metric === 'errors') appStats[appName].errors += numValue;
    }

    currentDate.setDate(currentDate.getDate() + 1);
  }

  // Convert to array and add calculated fields
  return Object.values(appStats).map(app => ({
    ...app,
    avgDuration: '—', // We don't track duration yet
  }));
}

async function getRecentFeedback(env, limit = 50) {
  const list = await env.ANALYTICS_KV.list({ prefix: 'feedback:' });
  const feedbackItems = [];

  // Fetch each feedback item (up to limit)
  for (const key of list.keys.slice(0, limit)) {
    const data = await env.ANALYTICS_KV.get(key.name);
    if (data) {
      try {
        feedbackItems.push(JSON.parse(data));
      } catch (e) {
        console.error('Failed to parse feedback:', e);
      }
    }
  }

  // Sort by timestamp (newest first)
  feedbackItems.sort((a, b) => 
    new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
  );

  return feedbackItems;
}

/* ===========================================
   UTILITY FUNCTIONS
   =========================================== */
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...CORS_HEADERS,
    },
  });
}

function getDateKey(date) {
  return date.toISOString().split('T')[0]; // Returns YYYY-MM-DD
}

function randomId() {
  return Math.random().toString(36).substring(2, 15);
}
