const BATCH_SIZE = 15;
const AUTO_REFRESH_MS = 15000;

const state = {
  allFeeds: [],
  filteredFeeds: [],
  trendingTags: [],
  commentsByFeedId: {},
  detailsByFeedId: {},
  sortMode: "latest",
  activeTag: "",
  keyword: "",
  visibleCount: BATCH_SIZE,
  dataSignature: "",
  timerId: null,
  isAutoRefreshOn: true,
  isRefreshing: false,
  activeCommentFeedId: "",
  activePostFeedId: "",
  commentPageByFeedId: {},
  commentHasMoreByFeedId: {},
  commentLoadingByFeedId: {},
  commentNoProgressByFeedId: {}
};

const refs = {
  tagBar: document.getElementById("tagBar"),
  searchForm: document.getElementById("searchForm"),
  searchInput: document.getElementById("searchInput"),
  sortSelect: document.getElementById("sortSelect"),
  resetBtn: document.getElementById("resetBtn"),
  refreshNowBtn: document.getElementById("refreshNowBtn"),
  toggleLiveBtn: document.getElementById("toggleLiveBtn"),
  stats: document.getElementById("stats"),
  liveState: document.getElementById("liveState"),
  dataStamp: document.getElementById("dataStamp"),
  feedGrid: document.getElementById("feedGrid"),
  loadMoreBtn: document.getElementById("loadMoreBtn"),
  commentModal: document.getElementById("commentModal"),
  commentMeta: document.getElementById("commentMeta"),
  commentList: document.getElementById("commentList"),
  loadMoreCommentsBtn: document.getElementById("loadMoreCommentsBtn"),
  closeCommentBtn: document.getElementById("closeCommentBtn"),
  commentTitle: document.getElementById("commentTitle"),
  postModal: document.getElementById("postModal"),
  postMeta: document.getElementById("postMeta"),
  postBody: document.getElementById("postBody"),
  postTitle: document.getElementById("postTitle"),
  closePostBtn: document.getElementById("closePostBtn"),
  imageModal: document.getElementById("imageModal"),
  imageViewer: document.getElementById("imageViewer")
};

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toSecureUrl(url) {
  const raw = String(url || "").trim();
  if (!raw) return "";
  if (raw.startsWith("//")) return `https:${raw}`;
  if (raw.startsWith("http://")) return `https://${raw.slice(7)}`;
  return raw;
}

function toProxyImageUrl(url) {
  const secure = toSecureUrl(url);
  if (!secure) return "";
  try {
    const u = new URL(secure);
    const host = u.hostname.toLowerCase();
    if (host === "image.coolapk.com" || host === "avatar.coolapk.com") {
      return `/img/${host}${u.pathname}${u.search}`;
    }
    return secure;
  } catch (_e) {
    return secure;
  }
}

function buildImageTag(url, alt, extraClass = "") {
  const secure = toSecureUrl(url);
  if (!secure) return "";
  const proxy = toProxyImageUrl(secure);
  const cls = extraClass ? `card-image ${extraClass}` : "card-image";
  return `<img class="${cls}" loading="lazy" referrerpolicy="no-referrer" src="${escapeHtml(proxy)}" data-fallback-src="${escapeHtml(secure)}" data-inline-toggle="1" alt="${escapeHtml(alt || "图片")}">`;
}

function applyImageFallback(container) {
  if (!container) return;
  const imgs = container.querySelectorAll("img[data-fallback-src]");
  imgs.forEach((img) => {
    if (img.dataset.fallbackBound === "1") return;
    img.dataset.fallbackBound = "1";
    img.addEventListener("error", () => {
      const fallback = img.dataset.fallbackSrc || "";
      if (!fallback || img.dataset.fallbackTried === "1") return;
      img.dataset.fallbackTried = "1";
      img.src = fallback;
    });
  });
}

function syncBodyLock() {
  const shouldLock =
    refs.commentModal.classList.contains("open") ||
    refs.postModal.classList.contains("open") ||
    refs.imageModal.classList.contains("open");
  document.body.style.overflow = shouldLock ? "hidden" : "";
}

function toggleInlineImage(imgEl) {
  if (!imgEl) return;
  imgEl.classList.toggle("expanded-inline");
}

function hasUsableDetail(detail) {
  if (!detail || typeof detail !== "object") return false;
  const pics = Array.isArray(detail.pics) ? detail.pics.filter(Boolean) : [];
  const message = String(detail.message || "").trim();
  const title = String(detail.message_title || "").trim();
  return pics.length > 0 || message.length > 0 || title.length > 0;
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  const now = Math.floor(Date.now() / 1000);
  const diff = Math.max(0, now - Number(timestamp));
  const minute = 60;
  const hour = 3600;
  const day = 86400;
  if (diff < minute) return "刚刚";
  if (diff < hour) return `${Math.floor(diff / minute)}分钟前`;
  if (diff < day) return `${Math.floor(diff / hour)}小时前`;
  if (diff < day * 7) return `${Math.floor(diff / day)}天前`;
  const d = new Date(Number(timestamp) * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function formatClock(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function normalizeMessage(rawMessage) {
  const plain = String(rawMessage || "").replace(/<[^>]*>/g, "");
  const escaped = escapeHtml(plain).replaceAll("\n", "<br>");
  return escaped.replace(/#([^#\n]+)#/g, (_m, tag) => {
    const safeTag = escapeHtml(tag.trim());
    return `<a class="inline-tag" href="#" data-tag="${safeTag}">#${safeTag}#</a>`;
  });
}

function normalizePlainText(raw) {
  const plain = String(raw || "").replace(/<[^>]*>/g, "");
  return escapeHtml(plain).replaceAll("\n", "<br>");
}

function toSearchBlob(feed) {
  return [
    feed.username,
    feed.device,
    feed.topic,
    feed.message,
    ...(Array.isArray(feed.tags) ? feed.tags : [])
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function buildSignature(data) {
  const feeds = Array.isArray(data && data.feeds) ? data.feeds : [];
  const comments = (data && data.commentsByFeedId && typeof data.commentsByFeedId === "object") ? data.commentsByFeedId : {};
  const details = (data && data.detailsByFeedId && typeof data.detailsByFeedId === "object") ? data.detailsByFeedId : {};

  const feedPart = feeds
    .slice(0, 30)
    .map((feed) => `${feed.id}-${feed.lastupdate || feed.dateline || 0}-${feed.replynum || 0}-${feed.likenum || 0}`)
    .join("|");

  const commentKeys = Object.keys(comments).sort();
  const commentPart = commentKeys
    .slice(0, 30)
    .map((feedId) => {
      const rows = Array.isArray(comments[feedId]) ? comments[feedId] : [];
      const first = rows[0] ? (rows[0].id || rows[0].dateline || 0) : 0;
      return `${feedId}:${rows.length}:${first}`;
    })
    .join("|");

  const detailKeys = Object.keys(details).sort();
  const detailPart = detailKeys
    .slice(0, 30)
    .map((feedId) => {
      const detail = details[feedId] || {};
      return `${feedId}:${detail.lastupdate || detail.dateline || 0}:${(detail.message || "").length}`;
    })
    .join("|");

  return `${feeds.length}::${feedPart}::${commentPart}::${detailPart}`;
}

function extractTrendingTags(data, feeds) {
  const derivedTags = new Set(
    (Array.isArray(data.trendingTags) ? data.trendingTags : [])
      .map((it) => it && it.name)
      .filter(Boolean)
  );
  for (const feed of feeds) {
    if (feed.topic) derivedTags.add(feed.topic);
  }
  return Array.from(derivedTags).slice(0, 10);
}

function applyFilters(resetVisible = true) {
  const keyword = state.keyword.trim().toLowerCase();
  const activeTag = state.activeTag;
  const filtered = state.allFeeds.filter((feed) => {
    const tags = Array.isArray(feed.tags) ? feed.tags : [];
    const matchTag = !activeTag || tags.includes(activeTag) || feed.topic === activeTag;
    if (!matchTag) return false;
    if (!keyword) return true;
    return toSearchBlob(feed).includes(keyword);
  });
  filtered.sort((a, b) => {
    const ta = Number(a.lastupdate || a.dateline || 0);
    const tb = Number(b.lastupdate || b.dateline || 0);
    if (state.sortMode === "oldest") return ta - tb;
    return tb - ta;
  });
  state.filteredFeeds = filtered;
  if (resetVisible) {
    state.visibleCount = BATCH_SIZE;
  }
}

function renderTagBar() {
  const chips = [];
  chips.push(`
    <button class="tag-chip ${state.activeTag === "" ? "active" : ""}" data-tag="">
      全部
    </button>
  `);
  for (const tag of state.trendingTags) {
    chips.push(`
      <button class="tag-chip ${state.activeTag === tag ? "active" : ""}" data-tag="${escapeHtml(tag)}">
        ${escapeHtml(tag)}
      </button>
    `);
  }
  refs.tagBar.innerHTML = chips.join("");
}

function renderStats() {
  const label = state.sortMode === "oldest" ? "最早" : "最新";
  refs.stats.textContent = `共 ${state.filteredFeeds.length} 条动态，当前显示 ${Math.min(state.visibleCount, state.filteredFeeds.length)} 条（${label}优先）`;
}

function renderLiveState(message = "") {
  const mode = state.isAutoRefreshOn ? `自动刷新开启（${AUTO_REFRESH_MS / 1000}秒）` : "自动刷新已暂停";
  refs.liveState.textContent = message ? `实时刷新：${mode}，${message}` : `实时刷新：${mode}`;
  refs.toggleLiveBtn.textContent = state.isAutoRefreshOn ? "暂停自动刷新" : "开启自动刷新";
}

function renderDataStamp(data) {
  const updatedAt = data && data.updatedAt ? String(data.updatedAt) : "未知";
  const source = data && data.source ? String(data.source) : "unknown";
  refs.dataStamp.textContent = `数据版本：${updatedAt}（${source}）`;
}

function renderGrid() {
  const view = state.filteredFeeds.slice(0, state.visibleCount);
  if (view.length === 0) {
    refs.feedGrid.innerHTML = `<article class="card"><div class="card-body"><p class="content">没有匹配到内容，换个关键词试试。</p></div></article>`;
    refs.loadMoreBtn.style.display = "none";
    renderStats();
    return;
  }

  refs.feedGrid.innerHTML = view.map((feed) => {
    const feedId = String(feed.id);
    const username = escapeHtml(feed.username || "酷友");
    const avatar = escapeHtml(toProxyImageUrl(feed.avatar));
    const device = escapeHtml(feed.device || "");
    const picHtml = Array.isArray(feed.pics) && feed.pics[0] ? buildImageTag(feed.pics[0], "动态图片", "preview") : "";
    const timeText = formatTime(feed.dateline);
    const message = normalizeMessage(feed.message);
    const likeNum = Number(feed.likenum) || 0;
    const replyNum = Number(feed.replynum) || 0;
    const hasCommentCache = Array.isArray(state.commentsByFeedId[feedId]) && state.commentsByFeedId[feedId].length > 0;

    return `
      <article class="card" data-id="${feedId}">
        <div class="card-body">
          <header class="card-head">
            <img class="avatar" loading="lazy" referrerpolicy="no-referrer" src="${avatar}" data-fallback-src="${escapeHtml(toSecureUrl(feed.avatar))}" alt="${username}">
            <div class="author-line">
              <span class="name">${username}</span>
              ${device ? `<span class="device">${device}</span>` : ""}
            </div>
          </header>
          <p class="content">${message}</p>
          ${picHtml}
          <footer class="foot">
            <span>${timeText}</span>
            <span class="engage">
              <span>评论 ${replyNum}</span>
              <span>赞 ${likeNum}</span>
              <span class="comment-entry">
                <button class="view-comment-btn" type="button" data-open-post="${feedId}">查看帖子</button>
              </span>
              <span class="comment-entry">
                <button class="view-comment-btn" type="button" data-open-comments="${feedId}">查看评论</button>
                ${hasCommentCache ? "" : "<span>未缓存</span>"}
              </span>
            </span>
          </footer>
        </div>
      </article>
    `;
  }).join("");

  refs.loadMoreBtn.style.display = state.visibleCount < state.filteredFeeds.length ? "inline-block" : "none";
  applyImageFallback(refs.feedGrid);
  renderStats();
}

function rerender() {
  renderTagBar();
  renderGrid();
}

function renderCommentModalContent(key, message = "") {
  const feed = state.allFeeds.find((it) => String(it.id) === key);
  const comments = Array.isArray(state.commentsByFeedId[key]) ? state.commentsByFeedId[key] : [];
  const titleName = feed && feed.username ? `${feed.username} 的评论` : "最新评论";
  refs.commentTitle.textContent = titleName;

  const total = feed ? Number(feed.replynum) || 0 : comments.length;
  if (comments.length > 0) {
    refs.commentMeta.textContent = `评论总数 ${total}，已加载 ${comments.length} 条`;
  } else {
    refs.commentMeta.textContent = message || `评论总数 ${total}，暂无评论缓存`;
  }

  if (comments.length === 0) {
    refs.commentList.innerHTML = `<article class="comment-item"><p class="comment-text">暂无评论。</p></article>`;
  } else {
    refs.commentList.innerHTML = comments.map((row) => {
      const avatar = escapeHtml(toProxyImageUrl(row.avatar));
      const name = escapeHtml(row.username || "酷友");
      const msg = normalizePlainText(row.message || "");
      const pic = row.pic ? buildImageTag(row.pic, "评论图片", "preview") : "";
      return `
        <article class="comment-item">
          <div class="comment-user">
            <img class="comment-avatar" src="${avatar}" data-fallback-src="${escapeHtml(toSecureUrl(row.avatar))}" alt="${name}" loading="lazy" referrerpolicy="no-referrer">
            <span class="comment-name">${name}</span>
          </div>
          <p class="comment-text">${msg}</p>
          ${pic}
          <footer class="comment-foot">
            <span>${formatTime(row.dateline)}</span>
            <span>赞 ${Number(row.likenum) || 0} · 回复 ${Number(row.replynum) || 0}</span>
          </footer>
        </article>
      `;
    }).join("");
  }
  applyImageFallback(refs.commentList);
  updateCommentLoadMoreButton(key);
}

function updateCommentLoadMoreButton(feedId) {
  const key = String(feedId || "");
  if (!key) {
    refs.loadMoreCommentsBtn.style.display = "none";
    return;
  }
  const loading = !!state.commentLoadingByFeedId[key];
  const hasMore = state.commentHasMoreByFeedId[key] !== false;
  refs.loadMoreCommentsBtn.disabled = loading;
  refs.loadMoreCommentsBtn.textContent = loading ? "加载中..." : "加载更多评论";
  refs.loadMoreCommentsBtn.style.display = hasMore ? "inline-block" : "none";
}

async function openCommentModal(feedId) {
  const key = String(feedId || "");
  if (!key) return;
  state.activeCommentFeedId = key;
  refs.commentModal.classList.add("open");
  refs.commentModal.setAttribute("aria-hidden", "false");
  syncBodyLock();
  const hasCache = Array.isArray(state.commentsByFeedId[key]) && state.commentsByFeedId[key].length > 0;
  state.commentPageByFeedId[key] = 0;
  state.commentHasMoreByFeedId[key] = true;
  state.commentNoProgressByFeedId[key] = 0;
  renderCommentModalContent(key, hasCache ? "已显示缓存评论，正在同步最新..." : "正在实时加载评论...");
  await loadCommentsPage(key, 1, true);
}

function closeCommentModal() {
  state.activeCommentFeedId = "";
  refs.commentModal.classList.remove("open");
  refs.commentModal.setAttribute("aria-hidden", "true");
  refs.loadMoreCommentsBtn.style.display = "none";
  syncBodyLock();
}

async function loadCommentsPage(feedId, page, replace = false) {
  const key = String(feedId || "");
  if (!key) return;
  if (state.commentLoadingByFeedId[key]) return;
  state.commentLoadingByFeedId[key] = true;
  updateCommentLoadMoreButton(key);

  try {
    const result = await fetchLiveReplies(key, page, 20);
    if (state.activeCommentFeedId !== key) return;
    const rows = result.rows || [];
    const existing = Array.isArray(state.commentsByFeedId[key]) ? state.commentsByFeedId[key] : [];
    const beforeCount = existing.length;
    if (replace) {
      state.commentsByFeedId[key] = rows;
    } else {
      const merged = [...existing];
      const seen = new Set(merged.map((r) => r.id));
      for (const row of rows) {
        if (!seen.has(row.id)) {
          merged.push(row);
          seen.add(row.id);
        }
      }
      state.commentsByFeedId[key] = merged;
    }
    const currentRows = Array.isArray(state.commentsByFeedId[key]) ? state.commentsByFeedId[key] : [];
    const afterCount = currentRows.length;
    const feed = state.allFeeds.find((it) => String(it.id) === key);
    const totalByFeed = Math.max(Number(result.total || 0) || 0, Number(feed?.replynum || 0) || 0);
    const hasMoreByApi = result.hasMore && rows.length > 0;
    const hasMoreByTotal = totalByFeed > 0 && afterCount < totalByFeed && page < 50;
    const noProgress = afterCount <= beforeCount;
    const noProgressCount = noProgress ? (Number(state.commentNoProgressByFeedId[key] || 0) + 1) : 0;
    state.commentNoProgressByFeedId[key] = noProgressCount;

    state.commentPageByFeedId[key] = page;
    const shouldStop = noProgressCount >= 2 && !hasMoreByApi;
    state.commentHasMoreByFeedId[key] = shouldStop ? false : (hasMoreByApi || hasMoreByTotal);

    let tip = "";
    if (result.source === "cache") {
      tip = "实时接口不可用，当前为缓存评论";
    }
    if (shouldStop && totalByFeed > afterCount) {
      tip = `当前仅加载 ${afterCount}/${totalByFeed} 条，实时翻页失败`;
    }
    renderCommentModalContent(key, tip);
  } catch (error) {
    if (state.activeCommentFeedId !== key) return;
    renderCommentModalContent(key, `实时加载失败：${error.message}`);
  } finally {
    state.commentLoadingByFeedId[key] = false;
    updateCommentLoadMoreButton(key);
  }
}

function renderPostModalContent(key, message = "") {
  const feed = state.allFeeds.find((it) => String(it.id) === key);
  const detail = state.detailsByFeedId[key] && typeof state.detailsByFeedId[key] === "object" ? state.detailsByFeedId[key] : {};
  const base = feed || {};
  const detailPics = Array.isArray(detail.pics) ? detail.pics.filter(Boolean) : [];
  const feedPics = Array.isArray(base.pics) ? base.pics.filter(Boolean) : [];
  const pics = detailPics.length > 0 ? detailPics : feedPics;

  refs.postTitle.textContent = `${detail.username || base.username || "酷友"} 的帖子`;
  refs.postMeta.textContent = `发布时间 ${formatTime(detail.dateline || base.dateline)} · 评论 ${Number(detail.replynum || base.replynum || 0)} · 赞 ${Number(detail.likenum || base.likenum || 0)}`;

  const titleHtml = detail.message_title ? `<h3 class="comment-name">${escapeHtml(detail.message_title)}</h3>` : "";
  const contentText = detail.message || base.message || "";
  const messageHtml = `<p class="post-message">${normalizePlainText(contentText)}</p>`;
  const tipHtml = message ? `<p class="comment-meta">${escapeHtml(message)}</p>` : "";
  const galleryHtml = pics.length > 0
    ? `<div class="post-gallery">${pics.map((url) => buildImageTag(url, "帖子图片", "preview")).join("")}</div>`
    : `<p class="comment-meta">该帖子当前未返回图片。</p>`;

  refs.postBody.innerHTML = `<article class="comment-item">${titleHtml}${tipHtml}${messageHtml}${galleryHtml}</article>`;
  applyImageFallback(refs.postBody);
}

async function openPostModal(feedId) {
  const key = String(feedId || "");
  if (!key) return;
  state.activePostFeedId = key;
  refs.postModal.classList.add("open");
  refs.postModal.setAttribute("aria-hidden", "false");
  syncBodyLock();

  renderPostModalContent(key, "正在实时加载帖子详情...");

  const hasCache = hasUsableDetail(state.detailsByFeedId[key]);
  if (hasCache) return;

  try {
    const detail = await fetchLiveDetail(key);
    if (state.activePostFeedId !== key) return;
    if (hasUsableDetail(detail)) {
      state.detailsByFeedId[key] = detail;
      renderPostModalContent(key);
    } else {
      renderPostModalContent(key, "实时接口未返回详情，已回退简版内容");
    }
  } catch (error) {
    if (state.activePostFeedId !== key) return;
    renderPostModalContent(key, `实时加载失败：${error.message}`);
  }
}

function closePostModal() {
  state.activePostFeedId = "";
  refs.postModal.classList.remove("open");
  refs.postModal.setAttribute("aria-hidden", "true");
  syncBodyLock();
}

function openImageModal(url) {
  const src = toSecureUrl(url);
  if (!src) return;
  refs.imageViewer.src = src;
  refs.imageModal.classList.add("open");
  refs.imageModal.setAttribute("aria-hidden", "false");
  syncBodyLock();
}

function closeImageModal() {
  refs.imageViewer.src = "";
  refs.imageModal.classList.remove("open");
  refs.imageModal.setAttribute("aria-hidden", "true");
  syncBodyLock();
}

function startAutoRefresh() {
  stopAutoRefresh();
  if (!state.isAutoRefreshOn) return;
  state.timerId = window.setInterval(() => {
    refreshData({ forceNetwork: true, fromAuto: true });
  }, AUTO_REFRESH_MS);
}

function stopAutoRefresh() {
  if (state.timerId) {
    window.clearInterval(state.timerId);
    state.timerId = null;
  }
}

async function loadData(forceNetwork = false) {
  const url = forceNetwork ? `./data/feeds.json?t=${Date.now()}` : `./data/feeds.json?t=${Date.now()}`;
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  } catch (error) {
    if (window.COOLAPK_FEED_DATA && Array.isArray(window.COOLAPK_FEED_DATA.feeds)) {
      return window.COOLAPK_FEED_DATA;
    }
    throw error;
  }
}

async function fetchLiveReplies(feedId, page = 1, rows = 20) {
  const response = await fetch(`/live/replies?id=${encodeURIComponent(feedId)}&page=${page}&rows=${rows}&t=${Date.now()}`, {
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`live replies HTTP ${response.status}`);
  }
  const data = await response.json();
  return {
    rows: Array.isArray(data.rows) ? data.rows : [],
    hasMore: !!data.hasMore,
    total: Number(data.total || 0) || 0,
    source: data.source || "unknown"
  };
}

async function fetchLiveDetail(feedId) {
  const response = await fetch(`/live/detail?id=${encodeURIComponent(feedId)}&t=${Date.now()}`, {
    cache: "no-store"
  });
  if (!response.ok) {
    throw new Error(`live detail HTTP ${response.status}`);
  }
  const data = await response.json();
  if (!data || !data.detail || typeof data.detail !== "object") return null;
  return hasUsableDetail(data.detail) ? data.detail : null;
}

function applyIncomingData(data, fromAuto) {
  const feeds = Array.isArray(data && data.feeds) ? data.feeds : [];
  const nextSignature = buildSignature(data);
  if (nextSignature === state.dataSignature) {
    return { changed: false, newCount: 0 };
  }

  const oldIds = new Set(state.allFeeds.map((feed) => feed.id));
  let newCount = 0;
  for (const feed of feeds) {
    if (!oldIds.has(feed.id)) newCount += 1;
  }

  state.allFeeds = feeds;
  state.commentsByFeedId = (data && data.commentsByFeedId && typeof data.commentsByFeedId === "object") ? data.commentsByFeedId : {};
  state.detailsByFeedId = (data && data.detailsByFeedId && typeof data.detailsByFeedId === "object") ? data.detailsByFeedId : {};
  state.trendingTags = extractTrendingTags(data, feeds);
  state.dataSignature = nextSignature;

  applyFilters(!fromAuto);
  rerender();

  if (state.activeCommentFeedId) {
    renderCommentModalContent(state.activeCommentFeedId);
  }
  if (state.activePostFeedId) {
    openPostModal(state.activePostFeedId);
  }

  return { changed: true, newCount };
}

async function refreshData({ forceNetwork = false, fromAuto = false } = {}) {
  if (state.isRefreshing) return;
  state.isRefreshing = true;
  refs.refreshNowBtn.disabled = true;

  try {
    const data = await loadData(forceNetwork);
    renderDataStamp(data);
    const result = applyIncomingData(data, fromAuto);
    const nowText = formatClock(new Date());

    if (!result.changed) {
      renderLiveState(`最后检查 ${nowText}，无新内容`);
    } else if (result.newCount > 0) {
      renderLiveState(`最后更新 ${nowText}，新增 ${result.newCount} 条`);
    } else {
      renderLiveState(`最后更新 ${nowText}`);
    }
  } catch (error) {
    renderLiveState(`刷新失败：${error.message}`);
  } finally {
    refs.refreshNowBtn.disabled = false;
    state.isRefreshing = false;
  }
}

function bindEvents() {
  refs.searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    state.keyword = refs.searchInput.value || "";
    applyFilters(true);
    rerender();
  });

  refs.resetBtn.addEventListener("click", () => {
    state.keyword = "";
    state.activeTag = "";
    refs.searchInput.value = "";
    applyFilters(true);
    rerender();
  });

  refs.sortSelect.addEventListener("change", () => {
    state.sortMode = refs.sortSelect.value === "oldest" ? "oldest" : "latest";
    applyFilters(true);
    rerender();
  });

  refs.refreshNowBtn.addEventListener("click", () => {
    refreshData({ forceNetwork: true, fromAuto: false });
  });

  refs.toggleLiveBtn.addEventListener("click", () => {
    state.isAutoRefreshOn = !state.isAutoRefreshOn;
    if (state.isAutoRefreshOn) {
      renderLiveState("自动刷新已恢复");
      startAutoRefresh();
      refreshData({ forceNetwork: true, fromAuto: true });
    } else {
      stopAutoRefresh();
      renderLiveState("自动刷新已暂停");
    }
  });

  refs.tagBar.addEventListener("click", (event) => {
    const target = event.target.closest(".tag-chip");
    if (!target) return;
    state.activeTag = target.dataset.tag || "";
    applyFilters(true);
    rerender();
  });

  refs.feedGrid.addEventListener("click", (event) => {
    const tagTarget = event.target.closest(".inline-tag");
    if (tagTarget) {
      event.preventDefault();
      state.activeTag = tagTarget.dataset.tag || "";
      applyFilters(true);
      rerender();
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }

    const commentBtn = event.target.closest("[data-open-comments]");
    if (commentBtn) {
      openCommentModal(commentBtn.dataset.openComments || "");
      return;
    }

    const postBtn = event.target.closest("[data-open-post]");
    if (postBtn) {
      openPostModal(postBtn.dataset.openPost || "");
      return;
    }

    const toggleImg = event.target.closest("img[data-inline-toggle='1']");
    if (toggleImg) {
      toggleInlineImage(toggleImg);
    }
  });

  refs.loadMoreBtn.addEventListener("click", () => {
    state.visibleCount += BATCH_SIZE;
    renderGrid();
  });

  refs.loadMoreCommentsBtn.addEventListener("click", async () => {
    const key = state.activeCommentFeedId;
    if (!key) return;
    const hasMore = state.commentHasMoreByFeedId[key] !== false;
    if (!hasMore) return;
    const nextPage = (state.commentPageByFeedId[key] || 1) + 1;
    await loadCommentsPage(key, nextPage, false);
  });

  refs.closeCommentBtn.addEventListener("click", closeCommentModal);
  refs.commentModal.addEventListener("click", (event) => {
    const closeEl = event.target.closest("[data-close='1']");
    if (closeEl) closeCommentModal();
    const toggleImg = event.target.closest("img[data-inline-toggle='1']");
    if (toggleImg) toggleInlineImage(toggleImg);
  });

  refs.closePostBtn.addEventListener("click", closePostModal);
  refs.postModal.addEventListener("click", (event) => {
    const closeEl = event.target.closest("[data-close-post='1']");
    if (closeEl) closePostModal();
    const toggleImg = event.target.closest("img[data-inline-toggle='1']");
    if (toggleImg) toggleInlineImage(toggleImg);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (refs.postModal.classList.contains("open")) {
      closePostModal();
      return;
    }
    if (refs.commentModal.classList.contains("open")) {
      closeCommentModal();
    }
  });
}

async function init() {
  bindEvents();
  renderLiveState();

  try {
    await refreshData({ forceNetwork: false, fromAuto: false });
    startAutoRefresh();
  } catch (error) {
    refs.stats.textContent = `数据加载失败：${error.message}`;
    refs.feedGrid.innerHTML = `<article class="card"><div class="card-body"><p class="content">数据加载失败，请检查 data/feeds.json 是否存在，或查看 docker sync 日志。</p></div></article>`;
    refs.loadMoreBtn.style.display = "none";
  }
}

init();
