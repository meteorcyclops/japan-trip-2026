import express from 'express';

const app = express();
app.use(express.json({ limit: '3mb' }));

const {
  PORT = '4318',
  PUBLISH_PASSWORD,
  GITHUB_TOKEN,
  GITHUB_OWNER,
  GITHUB_REPO,
  GITHUB_BRANCH = 'master',
  GITHUB_CONTENT_PATH = 'data/trip.json',
  GITHUB_VERSIONS_DIR = 'data/versions',
  ALLOWED_ORIGIN = 'https://travel.koxuan.com',
} = process.env;

function setCors(req, res) {
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
}

function normalizeValue(value) {
  if (Array.isArray(value)) {
    return value.map(normalizeValue);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, normalizeValue(v)]));
  }
  return value;
}

function collectChangedSections(before, after, path = '') {
  if (JSON.stringify(before) === JSON.stringify(after)) {
    return [];
  }

  const beforeIsObj = before && typeof before === 'object' && !Array.isArray(before);
  const afterIsObj = after && typeof after === 'object' && !Array.isArray(after);

  if (!beforeIsObj || !afterIsObj) {
    return [path || 'root'];
  }

  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  const changed = [];

  for (const key of keys) {
    const nextPath = path ? `${path}.${key}` : key;
    const sub = collectChangedSections(before?.[key], after?.[key], nextPath);
    changed.push(...sub);
  }

  return [...new Set(changed)];
}

function buildDiff(before, after, path = '') {
  if (JSON.stringify(before) === JSON.stringify(after)) {
    return [];
  }

  const beforeIsObj = before && typeof before === 'object' && !Array.isArray(before);
  const afterIsObj = after && typeof after === 'object' && !Array.isArray(after);

  if (!beforeIsObj || !afterIsObj) {
    return [{ path: path || 'root', before, after }];
  }

  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  const entries = [];
  for (const key of keys) {
    const nextPath = path ? `${path}.${key}` : key;
    entries.push(...buildDiff(before?.[key], after?.[key], nextPath));
  }
  return entries;
}

function base64Json(value) {
  return Buffer.from(JSON.stringify(value, null, 2) + '\n').toString('base64');
}

async function githubJson(url, headers, options = {}) {
  const res = await fetch(url, { headers, ...options });
  return { res, text: await res.text() };
}

app.options('/travel-publish', (req, res) => {
  setCors(req, res);
  res.status(204).end();
});

app.get('/healthz', (req, res) => {
  res.json({ ok: true, service: 'travel-publish-api' });
});

app.post('/travel-publish', async (req, res) => {
  setCors(req, res);

  try {
    const { password, content, message, editor = 'web-editor', source = 'editor.html' } = req.body || {};

    if (!PUBLISH_PASSWORD || !GITHUB_TOKEN || !GITHUB_OWNER || !GITHUB_REPO) {
      return res.status(500).json({ ok: false, error: 'server_not_configured' });
    }

    if (password !== PUBLISH_PASSWORD) {
      return res.status(401).json({ ok: false, error: 'invalid_password' });
    }

    if (!content || !Array.isArray(content.days) || !content.stays || !content.transportTips) {
      return res.status(400).json({ ok: false, error: 'invalid_content' });
    }

    const normalizedContent = normalizeValue(content);
    const timestamp = new Date().toISOString();
    const revisionId = timestamp.replaceAll(':', '-');
    const contentUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_CONTENT_PATH}`;
    const revisionPath = `${GITHUB_VERSIONS_DIR}/${revisionId}.json`;
    const revisionUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${revisionPath}`;
    const headers = {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'travel-publish-api',
    };

    const currentRes = await fetch(`${contentUrl}?ref=${encodeURIComponent(GITHUB_BRANCH)}`, { headers });
    if (!currentRes.ok) {
      const detail = await currentRes.text();
      return res.status(502).json({ ok: false, error: 'github_read_failed', detail });
    }

    const current = await currentRes.json();
    const beforeContent = JSON.parse(Buffer.from(current.content, 'base64').toString('utf8'));
    const changedSections = collectChangedSections(beforeContent, normalizedContent);
    const diff = buildDiff(beforeContent, normalizedContent);
    const revision = {
      revisionId,
      createdAt: timestamp,
      editor,
      source,
      message: message || `Update trip data (${timestamp})`,
      changedSections,
      diff,
      beforeSha: current.sha,
      beforeSnapshot: beforeContent,
      afterSnapshot: normalizedContent,
    };

    const commitMessage = message || `Update trip data from web editor (${timestamp})`;

    const revisionWrite = await githubJson(revisionUrl, headers, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: `${commitMessage} [revision]`,
        content: base64Json(revision),
        branch: GITHUB_BRANCH,
      }),
    });

    if (!revisionWrite.res.ok) {
      return res.status(502).json({ ok: false, error: 'github_revision_write_failed', detail: revisionWrite.text });
    }

    const writeRes = await fetch(contentUrl, {
      method: 'PUT',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: commitMessage,
        content: base64Json(normalizedContent),
        sha: current.sha,
        branch: GITHUB_BRANCH,
      }),
    });

    if (!writeRes.ok) {
      const detail = await writeRes.text();
      return res.status(502).json({ ok: false, error: 'github_write_failed', detail });
    }

    const result = await writeRes.json();
    return res.json({
      ok: true,
      commitSha: result.commit?.sha,
      commitUrl: result.commit?.html_url,
      revisionPath,
      revisionUrl: `https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/blob/${GITHUB_BRANCH}/${revisionPath}`,
      changedSections,
      revisionId,
    });
  } catch (error) {
    return res.status(500).json({ ok: false, error: 'server_error', detail: String(error) });
  }
});

app.listen(Number(PORT), () => {
  console.log(`travel-publish-api listening on :${PORT}`);
});
