/**
 * Cloudflare Worker — 微信公众号草稿箱发布中转
 *
 * 接收 GitHub Actions 发来的文章数据（HTML + base64 图片），
 * 调用微信公众平台 API 上传素材、创建草稿。
 *
 * 环境变量（wrangler secret put）:
 *   WECHAT_APPID      - 微信公众号 AppID
 *   WECHAT_APPSECRET  - 微信公众号 AppSecret
 *   WORKER_SECRET     - Worker 鉴权密钥
 */

const WECHAT_TOKEN_URL = 'https://api.weixin.qq.com/cgi-bin/token';
const WECHAT_MATERIAL_URL = 'https://api.weixin.qq.com/cgi-bin/material/add_material';
const WECHAT_DRAFT_URL = 'https://api.weixin.qq.com/cgi-bin/draft/add';

/**
 * 获取微信 access_token
 */
async function getAccessToken(appid, secret) {
  const url = `${WECHAT_TOKEN_URL}?grant_type=client_credential&appid=${appid}&secret=${secret}`;
  const resp = await fetch(url);
  const data = await resp.json();

  if (!data.access_token) {
    const errcode = data.errcode || '?';
    const errmsg = data.errmsg || 'unknown';
    throw new Error(`WeChat token failed [${errcode}]: ${errmsg}`);
  }

  return data.access_token;
}

/**
 * base64 → ArrayBuffer
 */
function base64ToArrayBuffer(base64) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

/**
 * 上传图片到微信（material/add_material）
 * @returns {string} 微信图床 URL
 */
async function uploadWeChatImage(token, imageBuffer, filename) {
  const url = `${WECHAT_MATERIAL_URL}?access_token=${token}&type=image`;

  const formData = new FormData();
  const blob = new Blob([imageBuffer], { type: 'image/jpeg' });
  formData.append('media', blob, filename);

  const resp = await fetch(url, { method: 'POST', body: formData });
  const data = await resp.json();

  if (!data.url) {
    const errcode = data.errcode || '?';
    throw new Error(`Upload image failed [${errcode}]: ${JSON.stringify(data)}`);
  }

  return data.url;
}

/**
 * 创建公众号草稿
 * @returns {{ media_id: string }}
 */
async function createDraft(token, { title, author, digest, content, thumb_media_id }) {
  const url = `${WECHAT_DRAFT_URL}?access_token=${token}`;

  const payload = {
    articles: [{
      title,
      author,
      digest,
      content,
      thumb_media_id,
      need_open_comment: 0,
      only_fans_can_comment: 1,
    }],
  };

  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  });
  const data = await resp.json();

  if (!data.media_id) {
    const errcode = data.errcode || '?';
    throw new Error(`Create draft failed [${errcode}]: ${JSON.stringify(data)}`);
  }

  return { media_id: data.media_id };
}

/**
 * 主处理函数
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 诊断端点：检查环境变量是否配置正确
    if (request.method === 'GET' && url.pathname === '/debug') {
      return new Response(JSON.stringify({
        WORKER_SECRET_set: !!env.WORKER_SECRET,
        WORKER_SECRET_len: (env.WORKER_SECRET || '').length,
        WECHAT_APPID_set: !!env.WECHAT_APPID,
        WECHAT_APPID_len: (env.WECHAT_APPID || '').length,
        WECHAT_APPSECRET_set: !!env.WECHAT_APPSECRET,
        WECHAT_APPSECRET_len: (env.WECHAT_APPSECRET || '').length,
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    }

    // 1. 验证密钥
    const secret = request.headers.get('X-Worker-Secret');
    if (secret !== env.WORKER_SECRET) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 2. 仅接受 POST
    if (request.method !== 'POST') {
      return new Response(JSON.stringify({ error: 'Method not allowed' }), {
        status: 405,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 3. 解析请求体
    let payload;
    try {
      payload = await request.json();
    } catch (e) {
      return new Response(JSON.stringify({ error: 'Invalid JSON body' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const { title, author, digest, content, cover_base64, images } = payload;

    if (!title || !content || !cover_base64) {
      return new Response(JSON.stringify({
        error: 'Missing required fields: title, content, cover_base64',
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    try {
      // 4. 获取 access_token
      console.log(`Getting access_token for appid: ${env.WECHAT_APPID?.substring(0, 6)}...`);
      const token = await getAccessToken(env.WECHAT_APPID, env.WECHAT_APPSECRET);

      // 5. 上传封面图
      console.log('Uploading cover...');
      const coverBuffer = base64ToArrayBuffer(cover_base64);
      const thumb_media_id = await uploadWeChatImage(token, coverBuffer, 'cover.jpg');
      console.log(`Cover uploaded: ${thumb_media_id}`);

      // 6. 上传文章内图片（QR 码等），替换占位符
      let html = content;
      for (const img of images || []) {
        console.log(`Uploading image: ${img.id}`);
        const imgBuffer = base64ToArrayBuffer(img.base64);
        const wxUrl = await uploadWeChatImage(token, imgBuffer, `${img.id}.png`);

        // 替换占位符 {{IMG:qr_0}}, {{IMG:qr_1}}, ...
        const placeholder = `{{IMG:${img.id}}}`;
        html = html.split(placeholder).join(wxUrl);
        console.log(`Replaced placeholder: ${placeholder}`);
      }

      // 7. 创建草稿
      console.log('Creating draft...');
      const result = await createDraft(token, {
        title,
        author: author || '卡拉库姆猫',
        digest: digest || '',
        content: html,
        thumb_media_id,
      });

      console.log(`Draft created: ${result.media_id}`);

      return new Response(JSON.stringify({
        success: true,
        media_id: result.media_id,
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });

    } catch (err) {
      console.error(`Error: ${err.message}`);
      return new Response(JSON.stringify({
        success: false,
        error: err.message,
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
};
