const API_BASE = "";
const ROUTES = { index: "/", game: "/game" };

const STATUS_LABEL = {
    finish: { badge: "挑戰完成", note: "成績已登上排行榜" },
    leaved: { badge: "中途離開", note: "這局不列入排行榜" },
    playing: { badge: "進行中", note: "遊戲尚未結束" },
    timeout: { badge: "逾時結束", note: "這局不列入排行榜" },
};

const el = Object.fromEntries([
    "resultSummary", "resultStatus", "statusBadge", "statusNote", "pointValue", "timeValue",
    "errorsPanel", "errorsCount", "errorsList", "errorsEmpty",
    "cctvImg", "cctvStatus",
    "rankingList", "rankingState", "refreshBtn", "againBtn",
].map((id) => [id, document.getElementById(id)]));

el.refreshBtn.addEventListener("click", loadRanking);
el.againBtn.addEventListener("click", replay);

const gameID = getGameID();
loadResult(gameID);
loadRanking();

function getGameID() {
    const fromQuery = new URLSearchParams(location.search).get("gameID");
    if (fromQuery) return fromQuery;
    try {
        return sessionStorage.getItem("gameID");
    } catch {
        return null;
    }
}

async function loadResult(id) {
    if (!id) {
        el.resultSummary.hidden = true;
        el.errorsPanel.hidden = true;
        return;
    }
    try {
        const data = await fetchResult(id);
        if (data.error) throw new Error(data.msg || "取得結算失敗");
        render(data);
    } catch (error) {
        el.statusBadge.textContent = "無法載入結算";
        el.statusNote.textContent = error.message;
        el.errorsPanel.hidden = true;
    }
}

function render(data) {
    const label = STATUS_LABEL[data.status] || { badge: data.status, note: "" };
    el.resultStatus.dataset.status = data.status;
    el.statusBadge.textContent = label.badge;
    el.statusNote.textContent = label.note;
    el.pointValue.textContent = `${data.point} 題`;
    el.timeValue.textContent = formatTime(data.total_time);

    const errors = data.error_question || [];
    el.errorsCount.textContent = errors.length;
    el.errorsList.replaceChildren();
    el.errorsEmpty.hidden = errors.length > 0;
    errors.forEach((question) => el.errorsList.appendChild(buildErrorCard(question)));

    const firstAnswer = errors[0]?.options?.find((option) => option.isAns) || errors[0]?.options?.[0];
    if (firstAnswer && firstAnswer.cctvID) selectCctv(firstAnswer.cctvID, firstAnswer.name);
}

function buildErrorCard(question) {
    const card = document.createElement("div");
    card.className = "error-card";

    const des = question.des || {};
    const head = document.createElement("div");
    head.className = "error-card-head";
    head.innerHTML = `<span class="error-road">${escapeHtml(des.name || "未知路線")}</span><span class="error-meta">${escapeHtml(des.dir || "")} ・ ${escapeHtml(des.mile || "")}</span>`;
    card.appendChild(head);

    const options = document.createElement("div");
    options.className = "error-options";
    (question.options || []).forEach((option) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "opt" + (option.isAns ? " correct" : "");
        button.innerHTML = `<span class="opt-name">${escapeHtml(option.name)}</span>` + (option.isAns ? '<span class="opt-tag">正解</span>' : "");
        if (option.cctvID) {
            button.addEventListener("click", () => selectCctv(option.cctvID, option.name, button));
        } else {
            button.disabled = true;
        }
        options.appendChild(button);
    });
    card.appendChild(options);
    return card;
}

async function selectCctv(cctvID, name, button) {
    document.querySelectorAll(".opt.active").forEach((other) => other.classList.remove("active"));
    if (button) button.classList.add("active");

    el.cctvImg.hidden = true;
    el.cctvStatus.hidden = false;
    el.cctvStatus.textContent = `載入「${name}」的即時影像…`;
    try {
        const src = await resolveCctvSrc(`${API_BASE}/api/cctv?ID=${encodeURIComponent(cctvID)}`);
        await showImage(el.cctvImg, src);
        el.cctvImg.hidden = false;
        el.cctvStatus.hidden = true;
    } catch {
        el.cctvStatus.textContent = "這支鏡頭暫時無法連線";
    }
}

async function resolveCctvSrc(endpoint) {
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const type = (response.headers.get("content-type") || "").toLowerCase();
    if (type.startsWith("image/") || type.startsWith("multipart/")) return endpoint;
    if (type.includes("json")) {
        const data = await response.json();
        return new URL(data.imageURL, location.href).href;
    }
    if (type.includes("html")) {
        const doc = new DOMParser().parseFromString(await response.text(), "text/html");
        const img = doc.querySelector("img[src]");
        if (img) return new URL(img.getAttribute("src"), location.href).href;
    }
    throw new Error("格式不支援");
}

function showImage(img, src) {
    return new Promise((resolve, reject) => {
        img.onload = () => resolve();
        img.onerror = () => reject(new Error("影像載入失敗"));
        img.src = src;
    });
}

async function loadRanking() {
    setRankState("載入中…");
    try {
        const data = await fetchRanking();
        if (data.error) throw new Error(data.msg || "取得排行榜失敗");
        renderRanking(data.ranking_list || []);
    } catch (error) {
        setRankState(`暫時無法載入排行榜：${error.message}`);
    }
}

function renderRanking(list) {
    el.rankingList.replaceChildren();
    if (!list.length) {
        setRankState("目前還沒有人上榜，快來搶頭香");
        return;
    }
    hideRankState();
    [...list]
        .sort((a, b) => b.score - a.score || a.time - b.time)
        .forEach((row, index) => {
            const rank = index + 1;
            const item = document.createElement("li");
            item.className = "rank-row";
            item.dataset.rank = rank;
            item.innerHTML = `<span class="rank-badge">${rank}</span><span class="rank-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</span><span class="rank-score">${row.score}</span><span class="rank-time">${formatTime(row.time)}</span>`;
            el.rankingList.appendChild(item);
        });
}

async function replay() {
    el.againBtn.disabled = true;
    const label = el.againBtn.querySelector(".glass-label");
    const original = label.textContent;
    label.textContent = "建立中…";

    let nickname = null;
    let email = null;
    try {
        nickname = sessionStorage.getItem("nickname") || null;
        email = sessionStorage.getItem("email") || null;
    } catch {}

    try {
        const data = await signIn({ nickname, email });
        if (data.error || !data.gameID) throw new Error(data.msg || "建立失敗");
        try {
            sessionStorage.setItem("gameID", data.gameID);
        } catch {}
        window.location.assign(ROUTES.game);
    } catch {
        label.textContent = original;
        el.againBtn.disabled = false;
        window.location.assign(ROUTES.index);
    }
}

async function signIn(payload) {
    const response = await fetch(`${API_BASE}/api/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

async function fetchResult(id) {
    const response = await fetch(`${API_BASE}/api/result?gameID=${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

async function fetchRanking() {
    const response = await fetch(`${API_BASE}/api/ranking`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

function formatTime(seconds) {
    const total = Number(seconds) || 0;
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return minutes > 0 ? `${minutes} 分 ${rest} 秒` : `${rest} 秒`;
}

function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (character) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
}

function setRankState(text) {
    el.rankingState.hidden = false;
    el.rankingState.textContent = text;
}

function hideRankState() {
    el.rankingState.hidden = true;
}
