(() => {
  "use strict";

  const state = {
    data: null,
    page: "chat",
    chat: [],
    busy: false,
    reviewMode: "daily",
    purchaseDraft: {},
  };

  const PAGE_META = {
    chat: { kicker: "智能经营", title: "经营工作台" },
    purchase: { kicker: "采购决策", title: "明日采购" },
    pricing: { kicker: "价格管理", title: "动态定价" },
    review: { kicker: "经营分析", title: "经营复盘" },
    data: { kicker: "数据管理", title: "数据中心" },
    memory: { kicker: "门店知识", title: "门店记忆" },
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const CHAT_STORAGE_KEY = "guoge_chat_v1";

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function attr(value) {
    return esc(value).replaceAll("\n", "&#10;");
  }

  function money(value, digits = 0) {
    const number = Number(value || 0);
    return `¥${number.toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })}`;
  }

  function localizedProvider(provider) {
    const value = String(provider || "");
    if (/[\u4e00-\u9fa5]/.test(value)) return value;
    if (/deepseek/i.test(value)) return "深度求索";
    if (/openai/i.test(value)) return "智能模型服务";
    return value ? "在线大模型" : "本地规则";
  }

  function localizedWeatherSource(source) {
    const value = String(source || "");
    return /[\u4e00-\u9fa5]/.test(value) ? value : "在线天气";
  }

  function number(value, digits = 0) {
    return Number(value || 0).toLocaleString("zh-CN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function icon(name) {
    return `<i data-lucide="${name}"></i>`;
  }

  function restoreChat() {
    try {
      const raw = localStorage.getItem(CHAT_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((item) => item && ["user", "assistant"].includes(item.role))
        .slice(-40);
    } catch (_error) {
      return [];
    }
  }

  function persistChat() {
    try {
      const compact = state.chat
        .filter((item) => ["user", "assistant"].includes(item.role))
        .slice(-40);
      localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(compact));
    } catch (_error) {
      // Local storage can be unavailable in private browser windows.
    }
  }

  function clearStoredChat() {
    try {
      localStorage.removeItem(CHAT_STORAGE_KEY);
    } catch (_error) {
      // Ignore storage failures.
    }
  }

  function historyPayload() {
    return state.chat
      .filter((item) => ["user", "assistant"].includes(item.role))
      .slice(-10)
      .map((item) =>
        item.role === "user"
          ? { role: "user", content: item.text || "" }
          : {
              role: "assistant",
              content: `${item.reply?.title || ""}：${item.reply?.text || ""}`.slice(0, 1600),
              context: item.reply?.context || null,
            }
      );
  }

  function refreshIcons() {
    if (window.lucide) {
      window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
    }
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.error || `请求失败（${response.status}）`);
    }
    return payload;
  }

  function activeMemories() {
    return (state.data?.memories || []).filter((memory) => memory.active);
  }

  function topRisk() {
    return state.data?.discount_plan?.[0] || null;
  }

  function planBudget() {
    return (state.data?.purchase_plan || []).reduce((sum, item) => sum + Number(item.budget || 0), 0);
  }

  function selectedPlanItems() {
    return (state.data?.purchase_plan || []).filter((item) => state.purchaseDraft[item.id]?.checked !== false);
  }

  function greeting() {
    const hour = new Date().getHours();
    if (hour < 6) return "夜深了";
    if (hour < 11) return "早上好";
    if (hour < 14) return "中午好";
    if (hour < 18) return "下午好";
    return "晚上好";
  }

  function updateShell() {
    const data = state.data;
    if (!data) return;
    $("#shop-name").textContent = data.store.name;
    $("#sync-label").textContent = `${data.context.sync_label} ${data.context.sync_time}`;
    $("#top-date").textContent = data.context.today_label;
    $("#purchase-nav-count").textContent = data.purchase_plan.length;
    $("#memory-nav-count").textContent = activeMemories().length;
    const weather = $(".weather-chip span");
    if (weather) weather.textContent = data.context.weather.temperature.replace("°C", "°C");

    const weatherMini = $("#sidebar-weather");
    if (weatherMini) {
      weatherMini.innerHTML = `
        <div class="weather-mini-top">
          <span>明日经营环境</span>
          ${icon(data.context.weather.icon || "cloud-sun")}
        </div>
        <div class="weather-mini-main">
          <strong>${esc(data.context.weather.temperature)}</strong>
          <span>${esc(data.context.weather.label)}</span>
        </div>
        <div class="weather-mini-note">明日客流预估 <b>${esc(data.context.traffic_lift)}</b></div>
      `;
    }
    refreshIcons();
  }

  function setPage(page) {
    if (!PAGE_META[page]) return;
    state.page = page;
    $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.page === page));
    $("#page-kicker").textContent = PAGE_META[page].kicker;
    $("#page-title").textContent = PAGE_META[page].title;
    const scroll = $("#content-scroll");
    scroll.classList.toggle("is-chat", page === "chat");
    scroll.scrollTop = 0;
    closeSidebar();
    renderPage();
  }

  function renderPage() {
    if (!state.data) return;
    updateShell();
    const root = $("#page-root");
    if (state.page === "chat") root.innerHTML = chatPage();
    if (state.page === "purchase") root.innerHTML = purchasePage();
    if (state.page === "pricing") root.innerHTML = pricingPage();
    if (state.page === "review") root.innerHTML = reviewPage();
    if (state.page === "data") root.innerHTML = dataPage();
    if (state.page === "memory") root.innerHTML = memoryPage();
    bindPageEvents();
    refreshIcons();
    if (state.page === "chat" && state.chat.length) {
      window.requestAnimationFrame(() => {
        const scroller = $("#content-scroll");
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
      });
    }
  }

  function bindPageEvents() {
    if (state.page === "chat") bindChat();
    if (state.page === "purchase") bindPurchase();
    if (state.page === "pricing") bindPricing();
    if (state.page === "review") bindReview();
    if (state.page === "data") bindData();
    if (state.page === "memory") bindMemory();
  }

  /* Chat */
  function welcomeHTML() {
    const data = state.data;
    const risk = topRisk();
    const plan = data.purchase_plan;
    const daily = data.reviews.daily;
    const revenue = data.kpis.revenue_yesterday;
    const orders = data.kpis.orders_yesterday;
    return `
      <section class="welcome-card welcome-bubble">
        <div class="welcome-top">今日经营简报</div>
        <h2>${greeting()}。<br />开店前，有 <em>3 件事</em> 值得先看一眼。</h2>
        <p class="welcome-intro">
          已同步 ${data.data_summary.order_days} 天订单和 ${data.data_summary.purchase_days} 天采购记录。
          明日采购、临期处理和昨日复盘均已更新。
        </p>
        <div class="welcome-insights">
          <button class="welcome-insight" type="button" data-goto="purchase">
            <span>${icon("shopping-basket")} 明日采购</span>
            <strong>${plan.length} 个商品，预算 ${money(planBudget())}</strong>
            <small>按实际天气、客流和近 7 天动销计算</small>
          </button>
          <button class="welcome-insight" type="button" data-goto="pricing">
            <span>${icon("alarm-clock")} 临期风险</span>
            <strong>${risk ? `${risk.name}建议 ${Number(risk.suggested_discount).toFixed(0)} 折` : "今日库存健康"}</strong>
            <small>${risk ? `预计减少 ${money(risk.loss_avoided)} 损耗` : "暂无紧急定价任务"}</small>
          </button>
          <button class="welcome-insight" type="button" data-goto="review">
            <span>${icon("chart-no-axes-combined")} 昨日经营</span>
            <strong>${money(revenue)} · ${orders} 单</strong>
            <small>${daily.metrics[0]?.change || "暂无同比数据"} · 较上周同日</small>
          </button>
        </div>
        <div class="welcome-shortcuts">
          <button class="welcome-shortcut" type="button" data-send="明天该进什么货？">${icon("sparkles")} 明天该进什么货？</button>
          <button class="welcome-shortcut" type="button" data-send="哪些水果要打折？">${icon("badge-percent")} 哪些水果要打折？</button>
          <button class="welcome-shortcut" type="button" data-send="总结一下昨天">${icon("notebook-pen")} 总结一下昨天</button>
        </div>
      </section>
    `;
  }

  function chatPage() {
    return `
      <div class="page-canvas">
        <div class="chat-layout">
          <section class="chat-panel">
            <div class="chat-scroll" id="chat-scroll">
              <div class="chat-feed" id="chat-feed">
                <div class="chat-date-separator">${esc(state.data.context.today_label)}</div>
                ${welcomeHTML()}
                ${state.chat.map(messageHTML).join("")}
              </div>
            </div>
            <div class="composer-wrap">
              <div class="quick-prompts">
                <button class="quick-prompt" type="button" data-send="明天该进什么货？">${icon("shopping-basket")} 采购建议</button>
                <button class="quick-prompt" type="button" data-send="哪些水果要打折？">${icon("badge-percent")} 动态定价</button>
                <button class="quick-prompt" type="button" data-send="总结一下昨天">${icon("notebook-pen")} 昨日复盘</button>
                <button class="quick-prompt" type="button" data-send="库存还有多少？">${icon("boxes")} 库存快照</button>
                <button class="quick-prompt" type="button" data-send="最近什么卖得最好？">${icon("trending-up")} 动销分析</button>
              </div>
              <form class="composer" id="chat-form">
                <textarea id="chat-input" rows="1" placeholder="问经营问题，或告诉果哥一条门店经验…"></textarea>
                <div class="composer-bottom">
                  <div class="composer-context">
                    <span class="live-dot"></span>
                    已连接订单、采购与门店记忆
                  </div>
                  <div class="composer-actions">
                    <button class="composer-tool" type="button" data-goto="data" aria-label="导入数据">${icon("paperclip")}</button>
                    <button class="composer-tool" type="button" data-send="明天天气会影响什么？" aria-label="明日环境">${icon("cloud-sun")}</button>
                    <button class="send-button" id="send-button" type="submit" aria-label="发送">${icon("arrow-up")}</button>
                  </div>
                </div>
              </form>
              <div class="composer-tip">果哥会基于门店数据回答 · 对话中的经验会自动沉淀到门店记忆</div>
            </div>
          </section>
          ${chatRail()}
        </div>
      </div>
    `;
  }

  function chatRail() {
    const data = state.data;
    const risk = topRisk();
    const memory = activeMemories()[0];
    const riskPct = risk ? Math.min(96, risk.risk_score) : 28;
    const llm = data.meta?.llm || {};
    const weather = data.context.weather;
    return `
      <aside class="rail-scroll">
        <section class="rail-card pulse-card">
          <div class="rail-card-top">
            <span class="rail-label">今日经营脉搏</span>
            <span class="rail-icon">${icon("activity")}</span>
          </div>
          <div class="pulse-headline">
            今天最该做的一件事：<br /><b>${risk ? `处理${risk.name}库存` : "按计划完成明日补货"}</b>
          </div>
          <p class="pulse-note">${risk ? `${risk.stock} ${risk.unit}库存可售 ${risk.days_cover} 天，执行后预计减少 ${money(risk.loss_avoided)} 损耗。` : "当前库存周转健康，重点放在明日销售机会。"}</p>
          <div class="pulse-gauge">
            <div class="risk-ring" style="--pct:${riskPct}">
              <span><strong>${riskPct}</strong><small>风险指数</small></span>
            </div>
            <div class="gauge-copy">
              <strong>${risk ? risk.urgency : "库存健康"}</strong>
              <span>${risk ? `${risk.when} · 建议 ${Number(risk.suggested_discount).toFixed(0)} 折` : "暂无高损耗风险商品"}</span>
            </div>
          </div>
          <button class="pulse-button" type="button" data-goto="pricing">
            <span>查看定价方案</span>
            ${icon("arrow-right")}
          </button>
        </section>

        <section class="rail-card">
          <div class="rail-card-top">
            <span class="rail-label">关键经营指标</span>
            <span class="pill pill-green">近 7 天</span>
          </div>
          <div class="rail-kpis">
            <div class="rail-kpi">
              <span>本周销售额</span>
              <strong>${money(data.kpis.week_revenue)}</strong>
              <small>${
                data.kpis.has_week_compare
                  ? `${data.kpis.week_change >= 0 ? "+" : ""}${number(data.kpis.week_change, 1)}%`
                  : "暂无上周数据"
              }</small>
            </div>
            <div class="rail-kpi">
              <span>综合毛利率</span>
              <strong>${number(data.kpis.gross_margin, 1)}%</strong>
              <small>健康区间</small>
            </div>
            <div class="rail-kpi">
              <span>库存金额</span>
              <strong>${money(data.kpis.inventory_value)}</strong>
              <small>20 个商品</small>
            </div>
            <div class="rail-kpi">
              <span>损耗风险</span>
              <strong>${money(data.kpis.risk_loss)}</strong>
              <small>${data.kpis.high_risk_count} 个高优 商品</small>
            </div>
          </div>
        </section>

        <section class="rail-card agent-card">
          <div class="rail-card-top">
            <span class="rail-label">智能助手状态</span>
            <span class="pill ${llm.connected ? "pill-green" : "pill-yellow"}">${llm.connected ? "在线" : "本地模式"}</span>
          </div>
          <div class="agent-status-list">
            <div><span>大模型</span><strong>${esc(localizedProvider(llm.provider))} · 大语言模型</strong></div>
            <div><span>实时天气</span><strong>${esc(localizedWeatherSource(weather.source))} · ${esc(weather.label)} ${esc(weather.temperature)}</strong></div>
            <div><span>数据日期</span><strong>${esc(data.context.today_label)}</strong></div>
          </div>
          <p class="agent-note">模型负责自然语言表达，库存、采购量和价格由经营工具计算。</p>
        </section>

        <section class="rail-card">
          <div class="rail-card-top">
            <span class="rail-label">门店记忆</span>
            ${icon("brain-circuit")}
          </div>
          <div class="memory-quote">
            <p>${esc(memory?.text || "还没有门店经验，告诉果哥一条你的进货直觉。")}</p>
            <small>${esc(memory?.tag || "门店经验")} · ${esc(memory?.impact || "参与经营计算")}</small>
          </div>
          <button class="rail-link" type="button" data-goto="memory">
            管理 ${activeMemories().length} 条记忆 ${icon("arrow-up-right")}
          </button>
        </section>
      </aside>
    `;
  }

  function messageHTML(message) {
    if (message.role === "user") {
      return `
        <div class="user-message">
          <div class="user-bubble">${esc(message.text)}</div>
        </div>
      `;
    }
    if (message.role === "typing") {
      return `
        <div class="assistant-reply">
          <div class="typing-bubble"><i></i><i></i><i></i></div>
        </div>
      `;
    }
    if (message.role === "error") {
      return `
        <div class="assistant-reply">
          <div class="ai-bubble"><h3>这次没有拿到数据</h3><p>${esc(message.text)}</p></div>
        </div>
      `;
    }
    return assistantReplyHTML(message.reply);
  }

  function assistantReplyHTML(reply) {
    if (!reply) return "";
    const table = reply.table ? chatTableHTML(reply.table) : "";
    const cards = reply.cards?.length
      ? `<div class="reply-cards">${reply.cards.map(replyCardHTML).join("")}</div>`
      : "";
    const bullets = reply.bullets?.length
      ? `<ul class="reply-bullets">${reply.bullets.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`
      : "";
    const actions = reply.actions?.length
      ? `<div class="reply-actions">${reply.actions
          .map(
            (action) =>
              `<button class="reply-action" type="button" data-action="${attr(action.action)}" data-payload="${attr(
                action.payload || ""
              )}">${esc(action.label)}${icon(
                action.action === "navigate" ? "arrow-up-right" : action.action === "download" ? "download" : "chevron-right"
              )}</button>`
          )
          .join("")}</div>`
      : "";
    const followups = reply.followups?.length
      ? `<div class="followups">${reply.followups
          .map((item) => `<button class="followup" type="button" data-send="${attr(item)}">${esc(item)}</button>`)
          .join("")}</div>`
      : "";
    const memoryPill = reply.memory
      ? `<div class="reply-actions" style="margin-top:9px"><span class="pill pill-green">${icon(
          "brain-circuit"
        )} 已沉淀到门店记忆</span></div>`
      : "";
    return `
      <div class="assistant-reply">
        <div class="ai-bubble">
          <h3>${esc(reply.title || "经营建议")}</h3>
          <p>${esc(reply.text || "")}</p>
          ${bullets}
          ${table}
          ${cards}
          ${memoryPill}
          ${actions}
          ${followups}
        </div>
      </div>
    `;
  }

  function chatTableHTML(table) {
    const headers = table.columns.map((column) => `<th>${esc(column)}</th>`).join("");
    const rows = table.rows
      .map((row) => {
        const values = Object.entries(row).filter(([key]) => key !== "name" && key !== "emoji");
        return `<tr><td><div class="mini-product"><b>${esc(row.name)}</b></div></td>${values
          .map(([, value]) => `<td class="mono">${esc(value)}</td>`)
          .join("")}</tr>`;
      })
      .join("");
    return `
      <div class="chat-table-wrap">
        <table class="chat-table">
          <thead><tr>${headers}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${table.footer ? `<div class="table-footer">${esc(table.footer)}</div>` : ""}
      </div>
    `;
  }

  function replyCardHTML(card) {
    return `
      <div class="reply-product-card">
        <div class="reply-card-copy">
          <strong>${esc(card.name)}</strong>
          <small>${esc(card.meta)}</small>
        </div>
        <span class="reply-card-value">${esc(card.value)}</span>
      </div>
    `;
  }

  function bindChat() {
    const form = $("#chat-form");
    const input = $("#chat-input");
    if (!form || !input) return;
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 110)}px`;
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      input.style.height = "auto";
      sendChat(text);
    });
    input.focus({ preventScroll: true });
  }

  async function sendChat(text) {
    if (state.busy || !text.trim()) return;
    state.busy = true;
    state.chat.push({ role: "user", text: text.trim() });
    persistChat();
    state.chat.push({ role: "typing" });
    if (state.page === "chat") renderPage();
    try {
      const history = historyPayload();
      const payload = await api("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text.trim(), history }),
      });
      state.chat = state.chat.filter((message) => message.role !== "typing");
      state.chat.push({ role: "assistant", reply: payload.reply });
      persistChat();
      state.data = payload.state;
      if (payload.reply?.type === "memory") {
        showToast("已加入门店记忆，后续建议会自动参考", "success");
      }
      renderPage();
    } catch (error) {
      state.chat = state.chat.filter((message) => message.role !== "typing");
      state.chat.push({ role: "error", text: error.message || "请稍后重试" });
      persistChat();
      renderPage();
    } finally {
      state.busy = false;
    }
  }

  /* Purchase */
  function ensurePurchaseDraft() {
    const plan = state.data.purchase_plan || [];
    plan.forEach((item) => {
      if (!state.purchaseDraft[item.id]) {
        state.purchaseDraft[item.id] = {
          qty: Number(item.recommended_qty),
          checked: item.confirmed ? false : true,
        };
      }
    });
  }

  function purchasePage() {
    ensurePurchaseDraft();
    const data = state.data;
    const plan = data.purchase_plan;
    const selected = selectedPlanItems();
    const draftBudget = selected.reduce(
      (sum, item) => sum + Number(state.purchaseDraft[item.id]?.qty || 0) * Number(item.unit_cost),
      0
    );
    const forecastRevenue = selected.reduce(
      (sum, item) => sum + Number(item.forecast_sales) * Number(item.unit_cost) * 1.86,
      0
    );
    const risk = topRisk();
    const strawberry = data.products.find((product) => product.id === "P003");
    const topPlan = plan[0] || null;
    const confirmed = plan.length > 0 && plan.every((item) => item.confirmed);
    return `
      <div class="page-canvas">
        <div class="page-intro">
          <div>
            <h2>明日采购</h2>
          </div>
          <div class="intro-actions">
            <button class="button" type="button" data-goto="data">${icon("upload")} 更新销售数据</button>
            <button class="button button-primary" type="button" id="copy-purchase">${icon("clipboard-list")} 复制采购单</button>
          </div>
        </div>

        <div class="metric-grid">
          <div class="metric-card accent">
            <div class="metric-label">${icon("wallet-cards")} 建议采购预算</div>
            <div class="metric-value" id="plan-budget-value">${money(draftBudget)}</div>
            <div class="metric-foot"><b>${selected.length}</b> 个商品 · 已结合天气与客流</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">${icon("smartphone")} 明日预估销售</div>
            <div class="metric-value">${money(forecastRevenue)}</div>
            <div class="metric-foot"><span class="trend-up">客流预估 ${data.context.traffic_lift}</span></div>
          </div>
          <div class="metric-card">
            <div class="metric-label">${icon("shield-check")} 预计减少损耗</div>
            <div class="metric-value">${money(risk?.loss_avoided || 0)}</div>
            <div class="metric-foot">通过停止采购 + 临期折扣</div>
          </div>
          <div class="metric-card warm">
            <div class="metric-label">${icon("brain-circuit")} 参考门店经验</div>
            <div class="metric-value">${activeMemories().length} <small>条</small></div>
            <div class="metric-foot">周末规律 · 损耗经验 · 社区洞察</div>
          </div>
        </div>

        <div class="purchase-layout">
          <section class="card">
            <div class="card-head">
              <div>
                <h3>${esc(data.context.tomorrow_label)} · 采购建议</h3>
              </div>
              <span class="pill ${confirmed ? "pill-green" : "pill-orange"}">${confirmed ? "已确认" : "待确认"}</span>
            </div>
            <div class="weather-banner">
              <div class="weather-icon">${icon(data.context.weather.icon)}</div>
              <div class="weather-copy">
                <strong>${esc(data.context.weather.label)} · ${esc(data.context.weather.temperature)} · 降雨 ${esc(
      data.context.weather.rain
    )}</strong>
                <small>${esc(data.context.weather.note)}，预计下午 16:00–18:30 出现销售峰值</small>
              </div>
              <div class="weather-tags">
                <span class="pill pill-orange">${icon("users")} 客流预估 ${esc(data.context.traffic_lift)}</span>
              </div>
            </div>
            <div class="data-table-wrap">
              <table class="data-table plan-table">
                <thead>
                  <tr>
                    <th style="width:30px"></th>
                    <th>商品</th>
                    <th>现有库存</th>
                    <th>明日预估</th>
                    <th>建议采购</th>
                    <th>采购金额</th>
                    <th>判断依据</th>
                  </tr>
                </thead>
                <tbody>
                  ${
                    plan.length
                      ? plan.map(purchaseRowHTML).join("")
                      : `<tr><td colspan="7"><div class="empty-state">${icon("database")}暂无采购建议，请先导入订单和采购数据</div></td></tr>`
                  }
                </tbody>
              </table>
            </div>
            <div class="plan-footer">
              <div class="plan-total">
                <span>合计</span>
                <strong id="plan-budget-footer">${money(draftBudget)}</strong>
                <small>预估到店成本</small>
              </div>
              <div class="plan-footer-actions">
                <button class="button" type="button" id="save-plan">${icon("bookmark")} 保存草稿</button>
                <button class="button button-primary" type="button" id="approve-purchase" ${confirmed ? "disabled" : ""}>
                  ${icon(confirmed ? "check-check" : "send")} ${confirmed ? "采购单已确认" : "确认采购单"}
                </button>
              </div>
            </div>
          </section>

          <aside class="insight-stack">
            <section class="rail-card opportunity-card">
              <div class="rail-card-top">
                <span class="rail-label">明日采购优先级</span>
                <span class="pill" style="background:rgba(255,255,255,.08);border-color:transparent;color:var(--lime)">${icon(
                  "trending-up"
                )} 高置信</span>
              </div>
              <div class="opportunity-main">
                <div>
                  <strong>${esc(topPlan?.name || "暂无建议")}</strong>
                  <small>${esc(topPlan?.reason || "导入数据后生成采购建议")}</small>
                </div>
              </div>
              <div class="opportunity-stats">
                <div class="opportunity-stat"><span>建议采购</span><strong>${topPlan ? `${purchaseQty(topPlan.id)} ${esc(topPlan.unit)}` : "0"}</strong></div>
                <div class="opportunity-stat"><span>预估销售</span><strong>${money(
                  topPlan ? forecastRevenueFor(topPlan.id) : 0
                )}</strong></div>
              </div>
              <button class="pulse-button" type="button" data-send="${attr(
                topPlan ? `为什么${topPlan.name}要进这么多？` : "明天该进什么货？"
              )}">
                <span>让果哥解释这个判断</span>${icon("arrow-right")}
              </button>
            </section>

            <section class="card">
              <div class="card-head">
                <div>
                  <h3>为什么这样建议</h3>
                  <p>所有因素都可解释、可追溯</p>
                </div>
              </div>
              <div class="factor-list">
                <div class="factor-item">
                  <div class="factor-icon orange">${icon("cloud-sun")}</div>
                  <div class="factor-copy">
                    <strong>天气与客流</strong>
                    <span>${esc(data.context.tomorrow_label)} ${esc(data.context.weather.label)} ${esc(
                      data.context.weather.temperature
                    )}，客流预估 ${esc(data.context.traffic_lift)}。</span>
                  </div>
                </div>
                <div class="factor-item">
                  <div class="factor-icon">${icon("chart-spline")}</div>
                  <div class="factor-copy">
                    <strong>近 7 天真实动销</strong>
                    <span>使用订单逐笔汇总，不按历史进货量倒推销量，避免把损耗误当成需求。</span>
                  </div>
                </div>
                <div class="factor-item">
                  <div class="factor-icon blue">${icon("brain-circuit")}</div>
                  <div class="factor-copy">
                    <strong>门店专属经验</strong>
                    <span>“草莓最多备 2 天销量”“周末西瓜提前备货”等经验已转换为计算约束。</span>
                  </div>
                </div>
              </div>
            </section>

            <div class="stop-buy">
              <div class="stop-buy-icon">${icon("octagon-alert")}</div>
              <div>
                <strong>草莓：今天停止采购</strong>
                <small>${
                  strawberry
                    ? `库存 ${number(strawberry.stock, 1)} ${strawberry.unit}，可售 ${number(
                        strawberry.days_cover,
                        1
                      )} 天，已接近货架期。先消化，再按隔日少量补货。`
                    : "当前没有需要暂停采购的短保商品。"
                }</small>
              </div>
            </div>
          </aside>
        </div>
      </div>
    `;
  }

  function purchaseRowHTML(item) {
    const draft = state.purchaseDraft[item.id] || { qty: item.recommended_qty, checked: true };
    const checked = draft.checked !== false;
    const amount = draft.qty * Number(item.unit_cost);
    return `
      <tr>
        <td>
          <button class="sku-check ${checked ? "checked" : ""}" type="button" data-sku-toggle="${attr(item.id)}" aria-label="选择商品">
            ${icon("check")}
          </button>
        </td>
        <td>
          <div class="table-product">
            <span class="table-product-name">
              <strong>${esc(item.name)}</strong>
              <small>${esc(item.category)} · 置信度 ${item.confidence}%</small>
            </span>
          </div>
        </td>
        <td class="mono">${number(item.current_stock)} ${esc(item.unit)}</td>
        <td class="mono">${number(item.forecast_sales)} ${esc(item.unit)}</td>
        <td>
          <div class="stepper">
            <button type="button" data-qty="${attr(item.id)}" data-delta="-1" aria-label="减少">−</button>
            <span data-qty-value="${attr(item.id)}">${number(draft.qty)} ${esc(item.unit)}</span>
            <button type="button" data-qty="${attr(item.id)}" data-delta="1" aria-label="增加">+</button>
          </div>
        </td>
        <td class="mono" data-amount="${attr(item.id)}">${money(amount)}</td>
        <td><div class="reason-cell">${esc(item.reason)}</div></td>
      </tr>
    `;
  }

  function purchaseQty(productId) {
    return number(state.purchaseDraft[productId]?.qty || 0);
  }

  function forecastRevenueFor(productId) {
    const item = state.data.purchase_plan.find((plan) => plan.id === productId);
    return item ? Number(item.forecast_sales) * Number(item.unit_cost) * 1.86 : 0;
  }

  function bindPurchase() {
    $$("[data-qty]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.qty;
        const delta = Number(button.dataset.delta);
        const draft = state.purchaseDraft[id];
        if (!draft) return;
        draft.qty = Math.max(0, Number(draft.qty) + delta);
        const item = state.data.purchase_plan.find((plan) => plan.id === id);
        const amountCell = $(`[data-amount="${CSS.escape(id)}"]`);
        const qtyValue = $(`[data-qty-value="${CSS.escape(id)}"]`);
        if (qtyValue) qtyValue.textContent = `${number(draft.qty)} ${item?.unit || ""}`;
        if (amountCell) amountCell.textContent = money(draft.qty * Number(item?.unit_cost || 0));
        updatePurchaseBudget();
      });
    });
    $$("[data-sku-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.skuToggle;
        const draft = state.purchaseDraft[id];
        if (!draft) return;
        draft.checked = !draft.checked;
        button.classList.toggle("checked", draft.checked);
        updatePurchaseBudget();
      });
    });
    $("#approve-purchase")?.addEventListener("click", approvePurchase);
    $("#copy-purchase")?.addEventListener("click", copyPurchase);
    $("#save-plan")?.addEventListener("click", () => showToast("采购草稿已保存在当前门店", "success"));
  }

  function updatePurchaseBudget() {
    const selected = selectedPlanItems();
    const draftBudget = selected.reduce(
      (sum, item) => sum + Number(state.purchaseDraft[item.id]?.qty || 0) * Number(item.unit_cost),
      0
    );
    const budgetValue = $("#plan-budget-value");
    const budgetFooter = $("#plan-budget-footer");
    if (budgetValue) budgetValue.textContent = money(draftBudget);
    if (budgetFooter) budgetFooter.textContent = money(draftBudget);
  }

  async function approvePurchase() {
    const ids = selectedPlanItems().map((item) => item.id);
    if (!ids.length) {
      showToast("至少选择一个商品", "error");
      return;
    }
    try {
      const payload = await api("/api/purchase/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      state.data = payload.state;
      state.purchaseDraft = {};
      showModal({
        title: "采购单已确认",
        subtitle: "果哥已把这次决策记录到经营日志",
        body: `
          <div class="upload-progress" style="padding-top:5px">
            <div class="upload-progress-icon">${icon("check-check")}</div>
            <h3>${ids.length} 个商品 已生成采购单</h3>
            <p>预计到店成本 ${money(planBudget())}。明天闭店后导入最新订单，我会自动验证这次判断是否准确。</p>
          </div>
        `,
        actions: `<button class="button button-primary" type="button" data-close-modal>知道了</button>`,
      });
      renderPage();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function copyPurchase() {
    const lines = selectedPlanItems().map(
      (item) => `${item.name} ${state.purchaseDraft[item.id]?.qty || item.recommended_qty} ${item.unit}`
    );
    await copyText(`明日采购单\n${lines.join("\n")}\n合计预算：${money(planBudget())}`);
    showToast("采购单已复制，可以直接发给供应商", "success");
  }

  /* Pricing */
  function pricingPage() {
    const data = state.data;
    const plan = data.discount_plan || [];
    const lossAvoided = plan.reduce((sum, item) => sum + Number(item.loss_avoided || 0), 0);
    const recovery = plan.reduce((sum, item) => sum + Number(item.expected_recovery || 0), 0);
    const minDiscount = Number(data.store.min_discount || 7);
    return `
      <div class="page-canvas">
        <div class="page-intro">
          <div>
            <h2>动态定价</h2>
          </div>
          <div class="intro-actions">
            <button class="button" type="button" id="copy-member-notice">${icon("message-circle")} 生成会员通知</button>
            <button class="button button-primary" type="button" id="apply-all-discounts">${icon("badge-check")} 执行全部建议</button>
          </div>
        </div>

        <div class="pricing-hero">
          <section class="pricing-hero-main">
            <div class="pricing-hero-copy">
              <span class="pill" style="background:rgba(255,255,255,.08);border-color:transparent;color:var(--lime)">${icon(
                "sparkles"
              )} 今日定价策略</span>
              <h2>${plan.length ? `先处理 <b>${esc(plan[0].name)}</b>，<br />${esc(plan[0].when)}是最佳窗口。` : "当前库存健康，<br />无需新增折扣。"}</h2>
              <p>${
                plan.length
                  ? `建议折扣组合预计回收 ${money(recovery)} 现金，减少 ${money(lossAvoided)} 潜在损耗。优先做组合装，维持正价商品的品牌感。`
                  : "果哥会继续监控库存与动销，出现临期风险时会主动提醒。"
              }</p>
            </div>
            <div class="pricing-hero-stat">
              <span>预计减少损耗</span>
              <strong>${money(lossAvoided)}</strong>
              <small>按当前库存和动销估算</small>
            </div>
          </section>
          <section class="card pricing-floor-card">
            <div class="pricing-floor-head">
              <div>
                <span class="rail-label">门店最低折扣</span>
                <strong>${minDiscount.toFixed(1)} 折</strong>
              </div>
              ${icon("badge-percent")}
            </div>
            <p>老板可以设置折扣下限，系统不会给出低于该折扣的定价建议。</p>
            <div class="pricing-floor-editor">
              <input class="text-field" id="min-discount-input" type="number" min="5" max="10" step="0.5" value="${minDiscount}" />
              <button class="button button-primary" type="button" id="save-min-discount">保存</button>
            </div>
            <small>可设置范围：5 折至 10 折</small>
          </section>
        </div>

        <div class="discount-grid">
          ${plan.length ? plan.map(discountCardHTML).join("") : emptyDiscountHTML()}
        </div>

        <section class="card">
          <div class="card-head">
            <div>
              <h3>执行后的预期效果</h3>
              <p>折扣执行后，系统会在下一次经营复盘中对比实际回收与预测</p>
            </div>
            <button class="button button-sm" type="button" data-goto="review">查看经营复盘 ${icon("arrow-up-right")}</button>
          </div>
          <div class="data-table-wrap">
            <table class="data-table">
              <thead><tr><th>商品</th><th>库存</th><th>可售天数</th><th>货架期</th><th>建议折扣</th><th>执行窗口</th><th>预计回收</th><th>减少损耗</th></tr></thead>
              <tbody>
                ${
                  plan.length
                    ? plan
                        .map(
                          (item) => `
                    <tr>
                      <td><div class="table-product"><span class="table-product-name"><strong>${esc(
                            item.name
                          )}</strong><small>${esc(item.bundle)}</small></span></div></td>
                      <td class="mono">${number(item.stock)} ${esc(item.unit)}</td>
                      <td class="mono">${number(item.days_cover, 1)} 天</td>
                      <td class="mono">${item.shelf_life} 天</td>
                      <td><span class="pill pill-orange">${Number(item.suggested_discount).toFixed(0)} 折</span></td>
                      <td>${esc(item.when)}</td>
                      <td class="mono">${money(item.expected_recovery)}</td>
                      <td class="mono">${money(item.loss_avoided)}</td>
                    </tr>`
                        )
                        .join("")
                    : `<tr><td colspan="8"><div class="empty-state">${icon("shield-check")}当前没有需要新增折扣的商品</div></td></tr>`
                }
              </tbody>
            </table>
          </div>
        </section>
      </div>
    `;
  }

  function discountCardHTML(item) {
    const applied = Boolean(item.applied);
    const urgent = item.risk_score >= 84;
    return `
      <article class="discount-card ${urgent ? "urgent" : ""}">
        ${applied ? `<span class="applied-ribbon">已执行</span>` : ""}
        <div class="discount-card-top">
          <div class="discount-title">
            <strong>${esc(item.name)}</strong>
            <small>${esc(item.risk_label)} · 可售 ${number(item.days_cover, 1)} 天</small>
            ${item.floor_applied ? `<span class="pill pill-yellow" style="margin-top:5px">受最低折扣约束</span>` : ""}
          </div>
          <div class="discount-value">
            <strong>${Number(item.suggested_discount).toFixed(0)}<span style="font-size:14px">折</span></strong>
            <small>${esc(item.when)}</small>
          </div>
        </div>
        <div class="risk-bar">
          <div class="risk-bar-top"><span>损耗风险</span><span>${item.risk_score} / 100</span></div>
          <div class="risk-track"><div class="risk-fill" style="width:${item.risk_score}%"></div></div>
        </div>
        <div class="discount-metrics">
          <div class="discount-metric"><span>现有库存</span><strong>${number(item.stock)} ${esc(item.unit)}</strong></div>
          <div class="discount-metric"><span>建议组合</span><strong>${esc(item.bundle.split(" ")[0])}</strong></div>
        </div>
        <p class="discount-reason">${esc(item.reason)}</p>
        <div class="discount-footer">
          <div class="discount-price">现价 <b>${money(item.discounted_price, 1)}</b></div>
          <button class="button button-sm ${applied ? "" : "button-primary"}" type="button" data-apply-discount="${attr(
      item.id
    )}" ${applied ? "disabled" : ""}>${applied ? "已执行" : "执行"}</button>
        </div>
      </article>
    `;
  }

  function emptyDiscountHTML() {
    return `<div class="card empty-state" style="grid-column:1/-1">${icon("shield-check")}<h3>今天没有临期风险</h3><p>果哥会继续监控库存与动销，出现风险时主动提醒你。</p></div>`;
  }

  function bindPricing() {
    $$("[data-apply-discount]").forEach((button) => {
      button.addEventListener("click", () => applyDiscounts([button.dataset.applyDiscount]));
    });
    $("#apply-all-discounts")?.addEventListener("click", () =>
      applyDiscounts((state.data.discount_plan || []).filter((item) => !item.applied).map((item) => item.id))
    );
    $("#copy-member-notice")?.addEventListener("click", copyMemberNotice);
    $("#save-min-discount")?.addEventListener("click", saveMinDiscount);
  }

  async function saveMinDiscount() {
    const value = Number($("#min-discount-input")?.value);
    if (!Number.isFinite(value) || value < 5 || value > 10) {
      showToast("最低折扣需在 5 折到 10 折之间", "error");
      return;
    }
    try {
      const payload = await api("/api/settings/min-discount", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ min_discount: value }),
      });
      state.data = payload.state;
      showToast(`最低折扣已更新为 ${value.toFixed(1)} 折`, "success");
      renderPage();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function applyDiscounts(ids) {
    if (!ids.length) {
      showToast("当前没有可执行的折扣", "error");
      return;
    }
    try {
      const payload = await api("/api/discount/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      state.data = payload.state;
      showToast(`${ids.length} 个折扣方案已执行`, "success");
      renderPage();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  async function copyMemberNotice() {
    const item = state.data.discount_plan?.[0];
    const text = item
      ? `【今日鲜果提醒】${item.name}今日 ${Number(item.suggested_discount).toFixed(0)} 折，搭配蓝莓做 ${item.bundle}，到手更划算。数量有限，卖完即止，欢迎到店挑选～`
      : "【今日鲜果提醒】门店鲜果今日供应充足，欢迎到店挑选～";
    await copyText(text);
    showToast("会员通知已复制", "success");
  }

  /* Review */
  function reviewPage() {
    const data = state.data;
    const review = data.reviews[state.reviewMode];
    const ranks = [...data.products].sort((a, b) => b.revenue_7d - a.revenue_7d).slice(0, 5);
    return `
      <div class="page-canvas">
        <div class="page-intro">
          <div>
            <h2>经营复盘</h2>
          </div>
          <div class="review-toolbar">
            <div class="segmented">
              <button type="button" data-review-mode="daily" class="${state.reviewMode === "daily" ? "active" : ""}">日报</button>
              <button type="button" data-review-mode="weekly" class="${state.reviewMode === "weekly" ? "active" : ""}">周报</button>
            </div>
            <button class="button" type="button" id="download-review">${icon("download")} 导出摘要</button>
          </div>
        </div>

        <div class="metric-grid">
          ${review.metrics
            .map(
              (metric, index) => `
              <div class="metric-card ${index === 0 ? "accent" : ""}">
                <div class="metric-label">${icon(index === 0 ? "wallet-cards" : index === 1 ? "receipt-text" : index === 2 ? "badge-dollar-sign" : "percent")} ${esc(
                metric.label
              )}</div>
                <div class="metric-value">${esc(metric.value)}</div>
                <div class="metric-foot"><span class="${metric.tone === "bad" ? "trend-down" : "trend-up"}">${esc(
                metric.change
              )}</span></div>
              </div>`
            )
            .join("")}
        </div>

        <div class="review-grid">
          <section class="card narrative-card">
            <span class="narrative-label">${icon("sparkles")} 果哥智能复盘</span>
            <h3>${esc(review.date_label)} 经营结论</h3>
            <p class="narrative-text">${esc(review.narrative)}</p>
            <div class="narrative-actions">
              <button class="button button-sm" type="button" data-send="${attr(
                state.reviewMode === "daily" ? "为什么昨天的损耗偏高？" : "下周应该重点改什么？"
              )}">${icon("message-circle-question")} 继续追问</button>
              <button class="button button-sm" type="button" data-goto="purchase">${icon("shopping-basket")} 调整明日采购</button>
            </div>
          </section>
          <section class="card chart-card">
            <div class="chart-head">
              <div><h3>近 7 天销售趋势</h3><p>销售额与毛利按日汇总</p></div>
              <div class="chart-legend">
                <span class="legend-item"><span class="legend-dot"></span>销售额</span>
                <span class="legend-item"><span class="legend-dot profit"></span>毛利</span>
              </div>
            </div>
            ${trendChart(data.trend)}
          </section>
        </div>

        <div class="review-bottom-grid">
          <section class="card insight-card">
            <div class="card-head" style="padding:0 0 10px">
              <div><h3>三个关键发现</h3></div>
            </div>
            ${review.insights
              .map(
                (insight) => `
                <div class="insight-item">
                  <div class="insight-item-top">
                    <span class="pill ${insight.type === "风险" ? "pill-red" : insight.type === "机会" ? "pill-yellow" : "pill-green"}">${esc(
                  insight.type
                )}</span>
                    <strong>${esc(insight.title)}</strong>
                  </div>
                  <p>${esc(insight.detail)}</p>
                </div>`
              )
              .join("")}
          </section>
          <section class="card">
            <div class="card-head">
              <div><h3>下一步行动</h3><p>果哥已按优先级排序</p></div>
              <span class="pill pill-green">${review.actions.length} 项</span>
            </div>
            <div class="action-list">
              ${review.actions
                .map(
                  (action, index) => `
                  <div class="action-row"><span class="action-index">${index + 1}</span><span>${esc(action)}</span></div>
                `
                )
                .join("")}
            </div>
          </section>
        </div>

        <div class="review-bottom-grid" style="margin-top:15px">
          <section class="card">
            <div class="card-head">
              <div><h3>近 7 天销售额贡献</h3><p>按商品销售额排序</p></div>
              <button class="button button-sm" type="button" data-goto="data">查看全部 ${icon("arrow-up-right")}</button>
            </div>
            <div class="rank-list">
              ${ranks
                .map(
                  (product, index) => `
                  <div class="rank-row">
                    <span class="rank-num">${String(index + 1).padStart(2, "0")}</span>
                    <span class="rank-name"><strong>${esc(product.name)}</strong><small>${number(product.sold_7d)} ${
                    product.unit
                  } · 毛利率 ${number(product.margin_rate, 1)}%</small></span>
                    <span class="rank-value"><strong>${money(product.revenue_7d)}</strong><small>${money(
                    product.profit_7d
                  )} 毛利</small></span>
                  </div>`
                )
                .join("")}
            </div>
          </section>
          <section class="card">
            <div class="card-head">
              <div><h3>本周损耗风险</h3><p>建议在风险发生前处理</p></div>
              <span class="pill pill-red">${money(data.kpis.risk_loss)}</span>
            </div>
            <div class="rank-list">
              ${[...data.products]
                .sort((a, b) => b.risk_score - a.risk_score)
                .slice(0, 4)
                .map(
                  (product) => `
                  <div class="rank-row">
                    <span class="rank-name"><strong>${esc(product.name)}</strong><small>可售 ${number(
                    product.days_cover,
                    1
                  )} 天 · 货架期 ${product.shelf_life} 天</small></span>
                    <span class="rank-value"><strong style="color:${product.risk_score >= 84 ? "var(--red)" : "var(--ink)"}">${product.risk_score}</strong><small>风险指数</small></span>
                  </div>`
                )
                .join("")}
            </div>
          </section>
        </div>
      </div>
    `;
  }

  function trendChart(trend) {
    if (!trend?.length) return `<div class="empty-state">暂无趋势数据</div>`;
    const width = 720;
    const height = 205;
    const pad = { left: 37, right: 12, top: 15, bottom: 25 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const maxValue = Math.max(...trend.map((item) => item.revenue)) * 1.08;
    const minValue = Math.min(...trend.map((item) => item.profit)) * 0.7;
    const x = (index) => pad.left + (index / Math.max(1, trend.length - 1)) * innerW;
    const y = (value) => pad.top + innerH - ((value - minValue) / Math.max(1, maxValue - minValue)) * innerH;
    const revenuePoints = trend.map((item, index) => `${x(index)},${y(item.revenue)}`).join(" ");
    const profitPoints = trend.map((item, index) => `${x(index)},${y(item.profit)}`).join(" ");
    const areaPath = `M ${pad.left} ${pad.top + innerH} L ${trend
      .map((item, index) => `${x(index)} ${y(item.revenue)}`)
      .join(" L ")} L ${x(trend.length - 1)} ${pad.top + innerH} Z`;
    const gridLines = [0, 0.25, 0.5, 0.75, 1]
      .map((ratio) => {
        const yPos = pad.top + innerH * ratio;
        const label = maxValue - (maxValue - minValue) * ratio;
        return `<line x1="${pad.left}" x2="${width - pad.right}" y1="${yPos}" y2="${yPos}" stroke="#ece9df" stroke-width="1" />
          <text x="${pad.left - 7}" y="${yPos + 3}" fill="#9ba198" font-size="8" text-anchor="end">${Math.round(
            label / 1000
          )}k</text>`;
      })
      .join("");
    return `
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="近14天销售额和毛利趋势">
        <defs>
          <linearGradient id="revenueArea" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2e6548" stop-opacity=".2"/>
            <stop offset="100%" stop-color="#2e6548" stop-opacity="0"/>
          </linearGradient>
        </defs>
        ${gridLines}
        <path d="${areaPath}" fill="url(#revenueArea)" />
        <polyline points="${revenuePoints}" fill="none" stroke="#2e6548" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round" />
        <polyline points="${profitPoints}" fill="none" stroke="#b7dc70" stroke-width="1.8" stroke-dasharray="4 4" stroke-linejoin="round" />
        ${trend
          .map(
            (item, index) =>
              `<circle cx="${x(index)}" cy="${y(item.revenue)}" r="${index === trend.length - 1 ? 4.6 : 2.5}" fill="${
                index === trend.length - 1 ? "#c8f17f" : "#fff"
              }" stroke="#2e6548" stroke-width="1.7" />`
          )
          .join("")}
        ${trend
          .map(
            (item, index) =>
              index % 2 === 0 || index === trend.length - 1
                ? `<text x="${x(index)}" y="${height - 6}" text-anchor="middle" fill="#9ba198" font-size="8">${esc(
                    item.label
                  )}</text>`
                : ""
          )
          .join("")}
      </svg>
    `;
  }

  function bindReview() {
    $$("[data-review-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.reviewMode = button.dataset.reviewMode;
        renderPage();
      });
    });
    $("#download-review")?.addEventListener("click", downloadReview);
  }

  function downloadReview() {
    const review = state.data.reviews[state.reviewMode];
    const content = `${review.date_label} 经营复盘\n\n${review.narrative}\n\n关键发现\n${review.insights
      .map((item) => `- ${item.title}：${item.detail}`)
      .join("\n")}\n\n下一步行动\n${review.actions.map((item, index) => `${index + 1}. ${item}`).join("\n")}`;
    downloadText(content, state.reviewMode === "daily" ? "昨日经营复盘.txt" : "本周经营复盘.txt");
    showToast("复盘摘要已导出", "success");
  }

  /* Data center */
  function dataPage() {
    const data = state.data;
    const inventory = [...data.products].sort((a, b) => a.stock - b.stock);
    const skuList = [...data.products].sort((a, b) => a.id.localeCompare(b.id));
    const qualityHealthy = data.quality.status === "healthy";
    const qualityEmpty = data.quality.status === "empty";
    return `
      <div class="page-canvas">
        <div class="page-intro">
          <div>
            <h2>数据中心</h2>
          </div>
          <div class="intro-actions">
            <button class="button button-danger-soft" type="button" id="clear-all-data">${icon("trash-2")} 清除全部数据</button>
            <button class="button" type="button" id="reset-demo">${icon("rotate-ccw")} 加载模拟数据</button>
            <a class="button button-primary" href="/api/export/inventory.xlsx">${icon("download")} 导出库存表</a>
          </div>
        </div>

        <div class="data-grid">
          <div>
            <div class="upload-column">
              ${uploadCardHTML(
                "orders",
                "订单明细",
                "",
                "导入所有订单后，系统按“日期 + 订单号 + 商品编码”去重，并汇总销量、销售额和毛利。",
                "green"
              )}
              ${uploadCardHTML(
                "purchases",
                "每日采购记录",
                "",
                "采购数量用于计算当前库存与成本，和订单销售合并后可得到可售天数和损耗风险。",
                "orange"
              )}
            </div>

            ${orderDetailsHTML(data)}
            ${purchaseDetailsHTML(data)}

            <section class="card inventory-card">
              <div class="card-head">
                <div><h3>库存与动销明细</h3><p>按当前库存从低到高排序 · 共 ${data.products.length} 个商品</p></div>
                <span class="pill ${data.quality.status === "healthy" ? "pill-green" : "pill-yellow"}">${icon("database")} ${
      data.data_summary.orders
    } 条订单</span>
              </div>
              <div class="data-table-wrap">
                <table class="data-table">
                  <thead><tr><th>商品</th><th>当前库存</th><th>近 7 天销量</th><th>可售天数</th><th>货架期</th><th>风险</th><th>库存金额</th></tr></thead>
                  <tbody>
                    ${inventory
                      .map(
                        (product) => `
                        <tr>
                          <td><div class="table-product"><span class="table-product-name"><strong>${esc(
                          product.name
                        )}</strong><small>${esc(product.category)} · ${esc(product.barcode)}</small></span></div></td>
                          <td class="mono">${number(product.stock, 1)} ${esc(product.unit)}</td>
                          <td class="mono">${number(product.sold_7d, 1)} ${esc(product.unit)}</td>
                          <td class="mono">${number(product.days_cover, 1)} 天</td>
                          <td class="mono">${product.shelf_life} 天</td>
                          <td><span class="pill ${
                            product.risk_score >= 84 ? "pill-red" : product.risk_score >= 62 ? "pill-yellow" : "pill-green"
                          }">${esc(product.risk_label)}</span></td>
                          <td class="mono">${money(product.stock_value)}</td>
                        </tr>`
                      )
                      .join("")}
                  </tbody>
                </table>
              </div>
            </section>

            <section class="card inventory-card">
              <div class="card-head">
                <div><h3>商品管理</h3><p>修改商品名称、品类、单位、成本、售价和货架期</p></div>
                <span class="pill">${data.products.length} 个商品</span>
              </div>
              <div class="data-table-wrap">
                <table class="data-table">
                  <thead><tr><th>编码</th><th>商品名称</th><th>品类</th><th>单位</th><th>成本</th><th>售价</th><th>货架期</th><th>操作</th></tr></thead>
                  <tbody>
                    ${skuList
                      .map(
                        (product) => `
                        <tr>
                          <td class="mono">编号 ${esc(product.id.replace(/\D/g, ""))}</td>
                          <td><strong>${esc(product.name)}</strong></td>
                          <td>${esc(product.category)}</td>
                          <td>${esc(product.unit)}</td>
                          <td class="mono">${money(product.cost, 2)}</td>
                          <td class="mono">${money(product.price, 2)}</td>
                          <td class="mono">${product.shelf_life} 天</td>
                          <td><button class="button button-sm" type="button" data-edit-sku="${attr(product.id)}">${icon(
                          "pencil"
                        )} 修改</button></td>
                        </tr>`
                      )
                      .join("")}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <aside class="insight-stack">
            <section class="card quality-card">
              <div class="card-head" style="padding:0">
                <div><h3>数据健康度</h3><p>导入后自动执行 5 项检查</p></div>
                <span class="pill ${qualityHealthy ? "pill-green" : "pill-yellow"}">${icon(
                  qualityHealthy ? "shield-check" : "circle-dashed"
                )} ${qualityHealthy ? "可用" : qualityEmpty ? "待导入" : "数据不完整"}</span>
              </div>
              <div class="quality-score">
                <div class="score-ring" style="--score:${data.quality.score}"><strong>${data.quality.score}</strong></div>
                <div><strong>${
                  qualityHealthy ? "数据完整，可以用于经营决策" : qualityEmpty ? "尚未导入经营数据" : "还需要另一类数据"
                }</strong><small>${qualityEmpty ? "上传表格文件后开始计算" : "订单与采购同时存在时，库存结果最准确"}</small></div>
              </div>
              <div class="quality-list">
                ${data.quality.checks
                  .map(
                    (check) => `
                    <div class="quality-row">
                      <span class="quality-check">${icon("check")}</span>
                      <strong>${esc(check.label)}</strong>
                      <small>${esc(check.detail)}</small>
                    </div>
                  `
                  )
                  .join("")}
              </div>
              <div class="data-summary-grid">
                <div class="data-summary-item"><strong>${data.data_summary.order_days}</strong><span>订单天数</span></div>
                <div class="data-summary-item"><strong>${data.purchase_plan.length}</strong><span>建议 商品</span></div>
                <div class="data-summary-item"><strong>${activeMemories().length}</strong><span>门店记忆</span></div>
              </div>
            </section>

            <section class="card">
              <div class="card-head" style="padding-bottom:10px">
                <div><h3>字段要求</h3><p>支持中英文列名，模板可直接下载</p></div>
              </div>
              <div style="padding:0 17px 16px">
                <div class="quality-row"><span class="quality-check">${icon("check")}</span><strong>订单必填</strong><small>日期 / 订单号 / 商品 / 数量</small></div>
                <div class="quality-row"><span class="quality-check">${icon("check")}</span><strong>采购必填</strong><small>日期 / 商品 / 采购数量 / 单价</small></div>
                <div class="quality-row"><span class="quality-check">${icon("check")}</span><strong>金额列</strong><small>可缺失，会按默认单价计算</small></div>
                <div class="upload-meta">
                  <a href="/api/template/orders.csv">订单分隔表格模板</a>
                  <span class="muted">·</span>
                  <a href="/api/template/orders.xlsx">订单电子表格模板</a>
                  <span class="muted">·</span>
                  <a href="/api/template/purchases.csv">采购分隔表格模板</a>
                  <span class="muted">·</span>
                  <a href="/api/template/purchases.xlsx">采购电子表格模板</a>
                </div>
              </div>
            </section>
          </aside>
        </div>
      </div>
    `;
  }

  function orderDetailsHTML(data) {
    const rows = (data.recent_orders || []).slice(0, 8);
    return `
      <section class="card inventory-card">
        <div class="card-head">
          <div><h3>订单明细</h3><p>已导入的订单流水，共 ${data.data_summary.orders} 条明细</p></div>
          <div style="display:flex;align-items:center;gap:7px">
            <span class="pill ${rows.length ? "pill-green" : "pill-yellow"}">${rows.length ? "订单已接入" : "暂无订单"}</span>
            <button class="button button-sm" type="button" data-all-records="orders">查看全部</button>
          </div>
        </div>
        <div class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>日期</th><th>订单号</th><th>商品</th><th>数量</th><th>销售额</th></tr></thead>
            <tbody>
              ${
                rows.length
                  ? rows
                      .map(
                        (row) => `
                        <tr>
                          <td>${esc(row.date)}</td>
                          <td class="mono">${esc(row.order_id)}</td>
                          <td>${esc(row.product_name)}</td>
                          <td class="mono">${number(row.quantity)} ${esc(row.unit || "")}</td>
                          <td class="mono">${money(row.amount, 2)}</td>
                        </tr>`
                      )
                      .join("")
                  : `<tr><td colspan="5"><div class="empty-state">${icon("receipt-text")}暂无订单明细，请先导入订单文件</div></td></tr>`
              }
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function purchaseDetailsHTML(data) {
    const rows = (data.recent_purchases || []).slice(0, 8);
    return `
      <section class="card inventory-card">
        <div class="card-head">
          <div><h3>采购明细</h3><p>已导入的采购流水，共 ${data.data_summary.purchases} 条明细</p></div>
          <div style="display:flex;align-items:center;gap:7px">
            <span class="pill ${rows.length ? "pill-green" : "pill-yellow"}">${rows.length ? "采购已接入" : "暂无采购"}</span>
            <button class="button button-sm" type="button" data-all-records="purchases">查看全部</button>
          </div>
        </div>
        <div class="data-table-wrap">
          <table class="data-table">
            <thead><tr><th>日期</th><th>采购单号</th><th>商品</th><th>采购数量</th><th>采购金额</th><th>供应商</th></tr></thead>
            <tbody>
              ${
                rows.length
                  ? rows
                      .map(
                        (row) => `
                        <tr>
                          <td>${esc(row.date)}</td>
                          <td class="mono">${esc(row.purchase_id)}</td>
                          <td>${esc(row.product_name)}</td>
                          <td class="mono">${number(row.quantity)} ${esc(row.unit || "")}</td>
                          <td class="mono">${money(row.amount, 2)}</td>
                          <td>${esc(row.supplier || "")}</td>
                        </tr>`
                      )
                      .join("")
                  : `<tr><td colspan="6"><div class="empty-state">${icon("shopping-basket")}暂无采购明细，请先导入采购文件</div></td></tr>`
              }
            </tbody>
          </table>
        </div>
      </section>
    `;
  }

  function uploadCardHTML(kind, title, subtitle, description, tone) {
    const isOrders = kind === "orders";
    return `
      <section class="card upload-card">
        <div class="upload-head">
          <span class="upload-icon ${tone === "orange" ? "orange" : ""}">${icon(isOrders ? "receipt-text" : "shopping-basket")}</span>
          <div><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></div>
          <span class="pill pill-green">${icon("check-circle-2")} 已连接</span>
        </div>
        <div class="dropzone" data-dropzone="${kind}">
          ${icon("cloud-upload")}
          <strong>拖拽表格文件到这里，或点击选择文件</strong>
          <span>支持分隔表格与电子表格 · 最大 12 兆 · 自动去重与字段校验</span>
          <input type="file" accept=".csv,.xlsx" data-upload-input="${kind}" />
        </div>
        <div style="margin-top:9px;color:var(--muted);font-size:13px;line-height:1.6">${esc(description)}</div>
        <div class="upload-meta">
          <a href="/api/sample/${kind}.csv">下载模拟分隔表格</a>
          <span class="muted">·</span>
          <a href="/api/sample/${kind}.xlsx">下载模拟电子表格</a>
          <span class="muted">·</span>
          <a href="/api/template/${kind}.xlsx">下载导入模板</a>
          <span class="muted">·</span>
          <button class="button button-ghost button-sm" type="button" data-send="我的表格要包含哪些列？" style="min-height:24px;padding:0 4px">问果哥 ${icon(
            "arrow-up-right"
          )}</button>
        </div>
      </section>
    `;
  }

  function bindData() {
    $$("[data-dropzone]").forEach((zone) => {
      const input = $("input[type=file]", zone);
      const kind = zone.dataset.dropzone;
      zone.addEventListener("click", (event) => {
        if (event.target !== input) input.click();
      });
      zone.addEventListener("dragover", (event) => {
        event.preventDefault();
        zone.classList.add("dragging");
      });
      zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
      zone.addEventListener("drop", (event) => {
        event.preventDefault();
        zone.classList.remove("dragging");
        const file = event.dataTransfer.files?.[0];
        if (file) handleUpload(file, kind);
      });
      input.addEventListener("change", () => {
        const file = input.files?.[0];
        if (file) handleUpload(file, kind);
        input.value = "";
      });
    });
    $("#reset-demo")?.addEventListener("click", confirmReset);
    $("#clear-all-data")?.addEventListener("click", confirmClearData);
    $$("[data-edit-sku]").forEach((button) => {
      button.addEventListener("click", () => openSkuEditor(button.dataset.editSku));
    });
    $$("[data-all-records]").forEach((button) => {
      button.addEventListener("click", () => openRecordsModal(button.dataset.allRecords, 0));
    });
  }

  async function openRecordsModal(kind, offset = 0) {
    const label = kind === "orders" ? "订单明细" : "采购明细";
    showModal({
      title: label,
      subtitle: "正在读取全部数据…",
      body: `<div class="empty-state">${icon("loader-circle")}正在加载</div>`,
    });
    try {
      const payload = await api(`/api/records?kind=${encodeURIComponent(kind)}&limit=50&offset=${offset}`);
      renderRecordsModal(kind, payload);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  function renderRecordsModal(kind, payload) {
    const isOrders = kind === "orders";
    const title = isOrders ? "订单明细" : "采购明细";
    const items = payload.items || [];
    const total = Number(payload.total || 0);
    const offset = Number(payload.offset || 0);
    const limit = Number(payload.limit || 50);
    const currentPage = Math.floor(offset / limit) + 1;
    const totalPages = Math.max(1, Math.ceil(total / limit));
    const headers = isOrders
      ? ["日期", "订单号", "商品", "数量", "单价", "销售额"]
      : ["日期", "采购单号", "商品", "采购数量", "采购单价", "采购金额", "供应商"];
    const rows = items
      .map((row) =>
        isOrders
          ? `<tr>
              <td>${esc(row.date)}</td>
              <td class="mono">${esc(row.order_id)}</td>
              <td>${esc(row.product_name)}</td>
              <td class="mono">${number(row.quantity)} ${esc(row.unit || "")}</td>
              <td class="mono">${money(row.unit_price, 2)}</td>
              <td class="mono">${money(row.amount, 2)}</td>
            </tr>`
          : `<tr>
              <td>${esc(row.date)}</td>
              <td class="mono">${esc(row.purchase_id)}</td>
              <td>${esc(row.product_name)}</td>
              <td class="mono">${number(row.quantity)} ${esc(row.unit || "")}</td>
              <td class="mono">${money(row.unit_cost, 2)}</td>
              <td class="mono">${money(row.amount, 2)}</td>
              <td>${esc(row.supplier || "")}</td>
            </tr>`
      )
      .join("");
    showModal({
      title,
      subtitle: `共 ${number(total)} 条，第 ${currentPage} / ${totalPages} 页`,
      body: `
        <div class="data-table-wrap" style="max-height:52vh;border:1px solid var(--line);border-radius:12px">
          <table class="data-table">
            <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
            <tbody>
              ${
                rows ||
                `<tr><td colspan="${headers.length}"><div class="empty-state">${icon("database")}暂无数据</div></td></tr>`
              }
            </tbody>
          </table>
        </div>
      `,
      actions: `
        <button class="button" type="button" data-close-modal>关闭</button>
        <button class="button" type="button" id="records-prev" ${offset <= 0 ? "disabled" : ""}>上一页</button>
        <button class="button button-primary" type="button" id="records-next" ${
          offset + limit >= total ? "disabled" : ""
        }>下一页</button>
      `,
    });
    $("#records-prev")?.addEventListener("click", () => openRecordsModal(kind, Math.max(0, offset - limit)));
    $("#records-next")?.addEventListener("click", () => openRecordsModal(kind, offset + limit));
  }

  function openSkuEditor(skuId) {
    const product = state.data.products.find((item) => item.id === skuId);
    if (!product) return;
    showModal({
      title: `修改商品 · 编号 ${product.id.replace(/\D/g, "")}`,
      subtitle: "修改后会重新计算采购建议、临期风险和经营指标",
      body: `
        <div class="memory-form-grid">
          <div>
            <label class="field-label" for="sku-name">商品名称</label>
            <input class="text-field" id="sku-name" value="${attr(product.name)}" />
          </div>
          <div>
            <label class="field-label" for="sku-category">品类</label>
            <input class="text-field" id="sku-category" value="${attr(product.category)}" />
          </div>
          <div>
            <label class="field-label" for="sku-unit">单位</label>
            <input class="text-field" id="sku-unit" value="${attr(product.unit)}" />
          </div>
          <div>
            <label class="field-label" for="sku-shelf">货架期（天）</label>
            <input class="text-field" id="sku-shelf" type="number" min="1" step="1" value="${product.shelf_life}" />
          </div>
          <div>
            <label class="field-label" for="sku-cost">成本（元）</label>
            <input class="text-field" id="sku-cost" type="number" min="0.01" step="0.01" value="${product.cost}" />
          </div>
          <div>
            <label class="field-label" for="sku-price">售价（元）</label>
            <input class="text-field" id="sku-price" type="number" min="0.01" step="0.01" value="${product.price}" />
          </div>
        </div>
      `,
      actions: `
        <button class="button" type="button" data-close-modal>取消</button>
        <button class="button button-primary" type="button" id="save-sku">${icon("save")} 保存修改</button>
      `,
    });
    $("#save-sku")?.addEventListener("click", async () => {
      const body = {
        id: skuId,
        name: $("#sku-name")?.value.trim(),
        category: $("#sku-category")?.value.trim(),
        unit: $("#sku-unit")?.value.trim(),
        shelf_life: Number($("#sku-shelf")?.value),
        cost: Number($("#sku-cost")?.value),
        price: Number($("#sku-price")?.value),
      };
      if (!body.name || !body.category || !body.unit) {
        showToast("商品名称、品类和单位不能为空", "error");
        return;
      }
      if (!(body.price > body.cost)) {
        showToast("售价必须高于成本", "error");
        return;
      }
      try {
        const payload = await api("/api/sku/update", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        state.data = payload.state;
        closeModal();
        showToast("商品已更新，经营建议已重新计算", "success");
        renderPage();
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  async function handleUpload(file, kind) {
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".xlsx") && !lowerName.endsWith(".csv")) {
      showToast("请上传支持的表格文件", "error");
      return;
    }
    showUploadProgress(file.name, kind);
    try {
      const payload = await api(`/api/upload?kind=${encodeURIComponent(kind)}`, {
        method: "POST",
        headers: {
          "Content-Type": lowerName.endsWith(".csv")
            ? "text/csv"
            : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "X-Filename": encodeURIComponent(file.name),
        },
        body: file,
      });
      const fill = $(".progress-fill");
      if (fill) fill.style.width = "100%";
      await new Promise((resolve) => setTimeout(resolve, 420));
      state.data = payload.state;
      closeModal();
      showToast(
        `已导入 ${payload.imported} 行${payload.skipped ? `，跳过 ${payload.skipped} 行重复数据` : ""}`,
        "success"
      );
      renderPage();
    } catch (error) {
      closeModal();
      showToast(error.message || "导入失败", "error");
    }
  }

  function showUploadProgress(filename, kind) {
    showModal({
      title: "正在导入数据",
      subtitle: kind === "orders" ? "订单明细" : "每日采购记录",
      body: `
        <div class="upload-progress">
          <div class="upload-progress-icon">${icon("file-spreadsheet")}</div>
          <h3>${esc(filename)}</h3>
          <p>正在匹配商品、校验字段并重算库存…</p>
          <div class="progress-track"><div class="progress-fill" style="width:38%"></div></div>
        </div>
      `,
    });
    setTimeout(() => {
      const fill = $(".progress-fill");
      if (fill) fill.style.width = "72%";
    }, 350);
  }

  function confirmReset() {
    showModal({
      title: "加载模拟数据？",
      subtitle: "这会替换当前导入的数据和操作记录",
      body: `<p style="margin:0;color:var(--muted);font-size:13px;line-height:1.7">系统会重新生成一套完整的模拟经营数据，适合演示或测试。当前修改不会保留。</p>`,
      actions: `
        <button class="button" type="button" data-close-modal>取消</button>
        <button class="button button-primary" type="button" id="confirm-reset">${icon("rotate-ccw")} 加载模拟数据</button>
      `,
    });
    $("#confirm-reset")?.addEventListener("click", async () => {
      try {
        const payload = await api("/api/reset", { method: "POST", body: "{}" });
        state.data = payload.state;
        state.purchaseDraft = {};
        state.chat = [];
        clearStoredChat();
        closeModal();
        showToast("已加载模拟数据", "success");
        setPage("data");
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  function confirmClearData() {
    showModal({
      title: "清除全部经营数据？",
      subtitle: "订单、采购记录、导入历史和计算建议都会被删除",
      body: `<p style="margin:0;color:var(--muted);font-size:13px;line-height:1.7">门店记忆会保留。清除后可以重新导入表格文件，也可以加载模拟数据恢复演示。</p>`,
      actions: `
        <button class="button" type="button" data-close-modal>取消</button>
        <button class="button button-danger-soft" type="button" id="confirm-clear-data">${icon("trash-2")} 确认清除</button>
      `,
    });
    $("#confirm-clear-data")?.addEventListener("click", async () => {
      try {
        const payload = await api("/api/data/clear", { method: "POST", body: "{}" });
        state.data = payload.state;
        state.purchaseDraft = {};
        state.chat = [];
        clearStoredChat();
        closeModal();
        showToast("全部经营数据已清除", "success");
        setPage("data");
      } catch (error) {
        showToast(error.message, "error");
      }
    });
  }

  /* Memory */
  function memoryPage() {
    const data = state.data;
    return `
      <div class="page-canvas">
        <div class="memory-hero">
          <div class="memory-hero-icon">${icon("brain-circuit")}</div>
          <div>
            <h2>门店记忆</h2>
          </div>
          <div class="memory-hero-stat">
            <strong>${activeMemories().length}</strong>
            <span>条生效记忆</span>
          </div>
        </div>

        <div class="memory-layout">
          <section class="card memory-list-card">
            <div class="card-head" style="padding:0 0 13px">
              <div><h3>门店记忆库</h3><p>停用的记忆不会参与计算，但会保留记录</p></div>
            </div>
            ${data.memories.map(memoryCardHTML).join("")}
          </section>

          <aside class="memory-side">
            <section class="card memory-form-card">
              <h3>告诉果哥一条经验</h3>
              <label class="field-label" for="memory-text">门店经验</label>
              <textarea class="text-field" id="memory-text"></textarea>
              <div class="memory-form-grid">
                <div>
                  <label class="field-label" for="memory-tag">归类</label>
                  <select class="select-field" id="memory-tag">
                    <option>经营经验</option>
                    <option>周末规律</option>
                    <option>天气经验</option>
                    <option>损耗经验</option>
                    <option>社区洞察</option>
                    <option>营销规则</option>
                  </select>
                </div>
                <div>
                  <label class="field-label" for="memory-impact">作用</label>
                  <select class="select-field" id="memory-impact">
                    <option>参与采购与定价计算</option>
                    <option>采购量约束</option>
                    <option>天气系数调整</option>
                    <option>选品与包装建议</option>
                    <option>活动提醒</option>
                  </select>
                </div>
              </div>
              <button class="button button-primary" type="button" id="add-memory">${icon("plus")} 加入门店记忆</button>
            </section>
          </aside>
        </div>
      </div>
    `;
  }

  function memoryCardHTML(memory) {
    return `
      <article class="memory-card ${memory.active ? "" : "inactive"}">
        <div class="memory-card-top">
          <span class="memory-tag">${esc(memory.tag)}</span>
          <time>${esc(memory.created_at)}</time>
          <button class="memory-toggle ${memory.active ? "on" : ""}" type="button" data-memory-toggle="${attr(
      memory.id
    )}" aria-label="启用或停用记忆"></button>
        </div>
        <p>${esc(memory.text)}</p>
        <div class="memory-card-foot">
          <span>来源：${esc(memory.source)}</span>
          <span>·</span>
          <b>${esc(memory.impact)}</b>
          <button type="button" data-memory-delete="${attr(memory.id)}">删除</button>
        </div>
      </article>
    `;
  }

  function bindMemory() {
    $$("[data-memory-toggle]").forEach((button) => {
      button.addEventListener("click", () => updateMemory({ action: "toggle", id: button.dataset.memoryToggle }));
    });
    $$("[data-memory-delete]").forEach((button) => {
      button.addEventListener("click", () =>
        updateMemory({ action: "delete", id: button.dataset.memoryDelete })
      );
    });
    $("#add-memory")?.addEventListener("click", async () => {
      const text = $("#memory-text")?.value.trim();
      if (!text) {
        showToast("先写一条门店经验", "error");
        return;
      }
      await updateMemory({
        action: "add",
        text,
        tag: $("#memory-tag")?.value || "经营经验",
        impact: $("#memory-impact")?.value || "参与采购与定价计算",
      });
      showToast("经验已加入门店记忆", "success");
    });
  }

  async function updateMemory(body) {
    try {
      const payload = await api("/api/memory", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      state.data = payload.state;
      renderPage();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  /* Modals and global interactions */
  function showModal({ title, subtitle, body, actions = "" }) {
    const root = $("#modal-root");
    root.innerHTML = `
      <div class="modal-backdrop" data-modal-backdrop>
        <div class="modal" role="dialog" aria-modal="true" aria-label="${attr(title)}">
          <div class="modal-head">
            <div><h3>${esc(title)}</h3>${subtitle ? `<p>${esc(subtitle)}</p>` : ""}</div>
            <button class="icon-button modal-close" type="button" data-close-modal aria-label="关闭">${icon("x")}</button>
          </div>
          <div class="modal-body">
            ${body}
            ${actions ? `<div class="modal-actions">${actions}</div>` : ""}
          </div>
        </div>
      </div>
    `;
    refreshIcons();
    $("[data-modal-backdrop]")?.addEventListener("click", (event) => {
      if (event.target === event.currentTarget) closeModal();
    });
  }

  function closeModal() {
    $("#modal-root").innerHTML = "";
  }

  function showToast(message, type = "success") {
    const root = $("#toast-root");
    const toast = document.createElement("div");
    toast.className = `toast ${type === "error" ? "error" : ""}`;
    toast.innerHTML = `${icon(type === "error" ? "circle-alert" : "check-circle-2")}<span>${esc(message)}</span>`;
    root.appendChild(toast);
    refreshIcons();
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(6px)";
      setTimeout(() => toast.remove(), 220);
    }, 3200);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_error) {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function performAction(button) {
    const action = button.dataset.action;
    const payload = button.dataset.payload || "";
    if (action === "navigate") setPage(payload);
    if (action === "toast") showToast(payload || "操作已完成", "success");
    if (action === "download") window.location.href = payload;
    if (action === "copy") {
      await copyText(payload);
      showToast("文案已复制", "success");
    }
  }

  function openSidebar() {
    $("#sidebar")?.classList.add("open");
    $("#sidebar-scrim")?.classList.add("visible");
  }

  function closeSidebar() {
    $("#sidebar")?.classList.remove("open");
    $("#sidebar-scrim")?.classList.remove("visible");
  }

  function showSettings() {
    const llm = state.data.meta.llm || {};
    const weather = state.data.context.weather || {};
    showModal({
      title: "门店设置",
      subtitle: "3.0 版本",
      body: `
        <div class="factor-list" style="padding:0">
          <div class="factor-item"><div class="factor-icon">${icon("store")}</div><div class="factor-copy"><strong>${esc(
        state.data.store.name
      )}</strong><span>${state.data.store.staff} 名员工</span></div></div>
          <div class="factor-item"><div class="factor-icon orange">${icon("database")}</div><div class="factor-copy"><strong>本地数据存储</strong><span>${
            state.data.data_summary.orders
          } 条订单 · ${state.data.data_summary.purchases} 条采购记录</span></div></div>
          <div class="factor-item"><div class="factor-icon blue">${icon("sparkles")}</div><div class="factor-copy"><strong>大模型</strong><span>${
            llm.connected ? "已连接" : "本地规则模式"
          } · ${esc(localizedProvider(llm.provider))} · 大语言模型</span></div></div>
          <div class="factor-item"><div class="factor-icon">${icon("cloud-sun")}</div><div class="factor-copy"><strong>实时天气</strong><span>${esc(
            localizedWeatherSource(weather.source)
          )} · ${esc(weather.label || "")} ${esc(weather.temperature || "")}</span></div></div>
          <div class="factor-item"><div class="factor-icon">${icon("badge-check")}</div><div class="factor-copy"><strong>智能助手版本</strong><span>3.0 版本</span></div></div>
        </div>
      `,
      actions: `
        <button class="button" type="button" data-close-modal>关闭</button>
        <button class="button" type="button" id="settings-reset">${icon("rotate-ccw")} 加载模拟数据</button>
      `,
    });
    $("#settings-reset")?.addEventListener("click", () => {
      closeModal();
      confirmReset();
    });
  }

  function bindGlobalEvents() {
    $$(".nav-item").forEach((button) => {
      button.addEventListener("click", () => setPage(button.dataset.page));
    });
    $("#mobile-menu")?.addEventListener("click", openSidebar);
    $("#sidebar-scrim")?.addEventListener("click", closeSidebar);
    $("#owner-settings")?.addEventListener("click", showSettings);
    $("#top-profile")?.addEventListener("click", showSettings);
    $("#shop-switch")?.addEventListener("click", showSettings);
    document.addEventListener("click", async (event) => {
      const close = event.target.closest("[data-close-modal]");
      if (close) {
        closeModal();
        return;
      }
      const send = event.target.closest("[data-send]");
      if (send) {
        event.preventDefault();
        setPage("chat");
        sendChat(send.dataset.send);
        return;
      }
      const go = event.target.closest("[data-goto]");
      if (go) {
        event.preventDefault();
        setPage(go.dataset.goto);
        return;
      }
      const action = event.target.closest("[data-action]");
      if (action) {
        event.preventDefault();
        await performAction(action);
        return;
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeModal();
        closeSidebar();
      }
    });
  }

  async function boot() {
    bindGlobalEvents();
    try {
      state.data = await api("/api/bootstrap");
      state.chat = restoreChat();
      updateShell();
      setPage("chat");
      setTimeout(() => $("#boot-screen")?.classList.add("hidden"), 320);
    } catch (error) {
      const bootScreen = $("#boot-screen");
      if (bootScreen) {
        bootScreen.innerHTML = `
          <div class="boot-name" style="font-size:18px;letter-spacing:0">无法连接果哥服务</div>
          <p style="max-width:320px;text-align:center;line-height:1.7">${esc(
            error.message
          )}<br/>请确认本地服务已启动后刷新页面。</p>
        `;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", boot);
})();



