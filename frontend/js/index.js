const API_BASE = "";
const ROUTES = { game: "/game", result: "/result" };

const form = document.getElementById("signinForm");
const nickname = document.getElementById("nickname");
const email = document.getElementById("email");
const emailHint = document.getElementById("emailHint");
const startBtn = document.getElementById("startBtn");
const statusBox = document.getElementById("statusBox");
const statusText = document.getElementById("statusText");
const ranImg = document.getElementById("rancctv");
const ranStatus = document.getElementById("rancctv-status");

email.addEventListener("input", () => {
    const value = email.value.trim();
    if (value && !isValidEmail(value)) {
        email.classList.add("invalid");
        emailHint.hidden = false;
        emailHint.textContent = "Email 格式看起來不太對";
    } else {
        email.classList.remove("invalid");
        emailHint.hidden = true;
    }
});

function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const emailValue = email.value.trim();
    if (emailValue && !isValidEmail(emailValue)) {
        setStatus("error", "請先修正 Email 再開始");
        return;
    }

    const payload = { nickname: nickname.value.trim() || null, email: emailValue || null };

    setLoading(true);
    setStatus("loading", "正在建立這一局…");
    try {
        const data = await signIn(payload);
        if (data.error) throw new Error(data.msg || "建立失敗");
        try {
            sessionStorage.setItem("gameID", data.gameID);
            sessionStorage.setItem("nickname", payload.nickname ?? "");
            sessionStorage.setItem("email", payload.email ?? "");
        } catch {}
        setStatus("success", "準備出發，祝你好運！");
        setTimeout(() => window.location.assign(ROUTES.game), 450);
    } catch (error) {
        setStatus("error", `暫時無法開始：${error.message}`);
        setLoading(false);
    }
});

async function signIn(payload) {
    const response = await fetch(`${API_BASE}/api/sign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

async function loadRandomPreview() {
    try {
        const src = await resolveCctvSrc(`${API_BASE}/api/rancctv`);
        await showImage(ranImg, src);
        ranImg.hidden = false;
        ranStatus.hidden = true;
    } catch {
        ranStatus.textContent = "即時影像暫時無法連線";
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
async function showImg(){
    ranImg.src=`${API_BASE}/api/rencctv`
    ranImg.hidden = false;
    ranStatus.hidden = true;
}
function setLoading(on) {
    startBtn.disabled = on;
    startBtn.classList.toggle("loading", on);
}

function setStatus(state, text) {
    statusBox.hidden = false;
    statusBox.dataset.state = state;
    statusText.textContent = text;
}
showImg();
// loadRandomPreview();