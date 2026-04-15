import express from 'express';

const app = express();
app.use(express.json({ limit: '1mb' }));

const {
  PORT = '4318',
  PUBLISH_PASSWORD,
  GITHUB_TOKEN,
  GITHUB_OWNER,
  GITHUB_REPO,
  GITHUB_BRANCH = 'master',
  GITHUB_CONTENT_PATH = 'data/trip.json',
  ALLOWED_ORIGIN = 'https://travel.koxuan.com',
} = process.env;

function setCors(req, res) {
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
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
    const { password, content, message } = req.body || {};

    if (!PUBLISH_PASSWORD || !GITHUB_TOKEN || !GITHUB_OWNER || !GITHUB_REPO) {
      return res.status(500).json({ ok: false, error: 'server_not_configured' });
    }

    if (password !== PUBLISH_PASSWORD) {
      return res.status(401).json({ ok: false, error: 'invalid_password' });
    }

    if (!content || !Array.isArray(content.days) || !content.stays || !content.transportTips) {
      return res.status(400).json({ ok: false, error: 'invalid_content' });
    }

    const baseUrl = `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_CONTENT_PATH}`;
    const headers = {
      'Authorization': `Bearer ${GITHUB_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'User-Agent': 'travel-publish-api'
    };

    const currentRes = await fetch(`${baseUrl}?ref=${encodeURIComponent(GITHUB_BRANCH)}`, { headers });
    if (!currentRes.ok) {
      const detail = await currentRes.text();
      return res.status(502).json({ ok: false, error: 'github_read_failed', detail });
    }

    const current = await currentRes.json();
    const payload = {
      message: message || `Update trip data from web editor (${new Date().toISOString()})`,
      content: Buffer.from(JSON.stringify(content, null, 2) + '\n').toString('base64'),
      sha: current.sha,
      branch: GITHUB_BRANCH,
    };

    const writeRes = await fetch(baseUrl, {
      method: 'PUT',
      headers: {
        ...headers,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
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
    });
  } catch (error) {
    return res.status(500).json({ ok: false, error: 'server_error', detail: String(error) });
  }
});

app.listen(Number(PORT), () => {
  console.log(`travel-publish-api listening on :${PORT}`);
});
