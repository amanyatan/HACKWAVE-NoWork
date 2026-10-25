/*
 * Code page: the generated HTML / CSS / JS project. File tabs and an editable editor beside a live preview, a real
 * live URL (http://127.0.0.1:<port>/p/<token>/) that opens in its own tab, and a ZIP download.
 * The live site is served from the other loopback name (localhost <-> 127.0.0.1), so it is a different origin from this app.
 */
(function () {
  const { h } = NW;
  const view = document.getElementById("view-code");
  const CACHE_KEY = "nw_code_project";
  const HINTS = ["Reading your prompts…", "Planning the screens…", "Writing index.html…", "Styling with style.css…", "Wiring up script.js…", "Checking everything fits together…"];

  let status = "empty"; // empty | generating | ready | error
  let project = null; // { title, files: [{ path, content }], saved }
  let request = null; // last payload, kept for Retry
  let error = "";
  let activePath = null;
  let hintTimer = null;
  let runTimer = null;
  let liveToken = null; // server-side token of the live site
  let liveUrl = "";
  let layout = innerWidth >= 1000 ? "split" : "code"; // code | split | preview
  let el = {}; // editor / preview handles while the project view is on screen
  const LOOPBACK = ["localhost", "127.0.0.1"];

  NW.codeStatus = () => status;

  const cache = () => { try { localStorage.setItem(CACHE_KEY, JSON.stringify(project)); } catch {} };
  const cached = () => { try { return JSON.parse(localStorage.getItem(CACHE_KEY) || "null"); } catch { return null; } };

  /* ---------- called when the agent asked for code ---------- */
  NW.codeRequested = (payload) => {
    request = payload;
    generate();
  };

  async function generate() {
    status = "generating";
    error = "";
    render();
    if (NW.route() === "prompt") NW.pages.prompt.refresh();
    try {
      const r = await NW.api("/api/code", {
        method: "POST",
        timeout: 170000,
        body: { client_id: NW.clientId, set_id: request.setId, title: request.title, summary: request.summary, ai_tool: request.aiTool, steps: request.steps.map(({ title, prompt }) => ({ title, prompt })) },
      });
      project = { id: r.id, title: r.title, files: r.files, saved: r.saved };
      activePath = (project.files.find((f) => f.path === "index.html") || project.files[0]).path;
      cache();
      status = "ready";
      if (NW.route() !== "code") NW.badge("code", true);
    } catch (e) {
      status = "error";
      error = e.status === 429 ? "Too many code requests right now. Please wait a few minutes and retry." : e.message;
    }
    clearInterval(hintTimer);
    if (NW.route() === "code") render();
    else if (NW.route() === "prompt") NW.pages.prompt.refresh(); // drop the "being prepared" banner
  }

  /* ---------- preview ---------- */
  // Generated apps use localStorage, which a sandboxed iframe (no same-origin) is not allowed to touch, so give it an in-memory one.
  const POLYFILL =
    "<script>(function(){function mk(){var m={};return{getItem:function(k){return Object.prototype.hasOwnProperty.call(m,k)?m[k]:null},setItem:function(k,v){m[k]=String(v)},removeItem:function(k){delete m[k]},clear:function(){m={}},key:function(i){return Object.keys(m)[i]||null},get length(){return Object.keys(m).length}}}" +
    "['localStorage','sessionStorage'].forEach(function(n){try{Object.defineProperty(window,n,{value:mk(),configurable:true})}catch(e){}})})()</" + "script>";

  const clean = (p) => p.replace(/^\.?\//, "");
  function buildPreview(files) {
    const by = Object.fromEntries(files.map((f) => [f.path, f.content]));
    let html = by["index.html"] ?? "<p style='font-family:sans-serif'>index.html is missing.</p>";
    html = html.replace(/<link\b[^>]*>/gi, (tag) => {
      const href = (/href=["']([^"']+)["']/i.exec(tag) || [])[1];
      return href && /stylesheet/i.test(tag) && by[clean(href)] != null ? `<style>${by[clean(href)]}</style>` : tag;
    });
    html = html.replace(/<script\b([^>]*)>\s*<\/script>/gi, (tag, attrs) => {
      const src = (/src=["']([^"']+)["']/i.exec(attrs) || [])[1];
      return src && by[clean(src)] != null ? `<script>${by[clean(src)].replace(/<\/script/gi, "<\\/script")}</` + "script>" : tag;
    });
    return /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, (m) => m + POLYFILL) : POLYFILL + html;
  }
  /** Where the live site lives: the other loopback name, so it can never share an origin (and storage) with this app. */
  function siteOrigin() {
    const h = location.hostname;
    if (!LOOPBACK.includes(h)) return location.origin;
    return `${location.protocol}//${h === "localhost" ? "127.0.0.1" : "localhost"}${location.port ? `:${location.port}` : ""}`;
  }

  /** Publish the current files as the live site and point the preview at it. */
  async function runPreview() {
    if (!el.frame || !project) return;
    try {
      const r = await NW.api("/api/preview", { method: "POST", body: { files: project.files, token: liveToken } });
      liveToken = r.token;
      liveUrl = `${siteOrigin()}/p/${liveToken}/`;
      el.live.value = liveUrl;
      el.open.disabled = el.copyLink.disabled = false;
      el.frame.removeAttribute("srcdoc");
      el.frame.src = `${liveUrl}?v=${Date.now()}`; // cache-buster: reload with the latest edits
    } catch {
      el.live.value = "Live link unavailable (is the server running?)";
      el.frame.srcdoc = buildPreview(project.files); // the in-page preview still works without the server's help
    }
  }

  /* ---------- editor ---------- */
  const fileOf = (path) => project.files.find((f) => f.path === path);
  const ext = (path) => (path.split(".").pop() || "").toLowerCase();

  function openFile(path) {
    activePath = path;
    el.code.value = fileOf(path).content;
    el.tabs.querySelectorAll(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.path === path)));
    el.code.scrollTop = 0;
  }

  /* ---------- views ---------- */
  function shell(...kids) {
    return h("div", { class: "page-inner" }, ...kids);
  }

  function emptyView() {
    return shell(
      h("h1", {}, "Code"),
      h("p", { class: "lede" }, "Ready-to-run starter code for your idea."),
      h("div", { class: "empty", style: "margin-top:20px" },
        h("h2", {}, "No code yet"),
        h("p", {}, "Tell your agent you want the prompts and the code. As a beta, it can write a simple HTML, CSS and JavaScript project that opens right in your browser."),
        h("a", { class: "nb-btn primary", href: "#/agents" }, "Go to Agents"))
    );
  }

  function generatingView() {
    const hint = h("p", {}, HINTS[0]);
    let i = 0;
    clearInterval(hintTimer);
    hintTimer = setInterval(() => { i = (i + 1) % HINTS.length; hint.textContent = HINTS[i]; }, 3500);
    return shell(
      h("h1", {}, request?.title || "Your code"),
      h("div", { class: "gen" }, h("h2", {}, "Writing your code…"), hint, h("div", { class: "progress-bar" }, h("i")), h("p", {}, "This usually takes under a minute. You can keep downloading prompts meanwhile."))
    );
  }

  function errorView() {
    return shell(
      h("h1", {}, request?.title || "Your code"),
      h("div", { class: "gen" }, h("h2", {}, "Could not write the code"), h("p", { class: "err" }, error), h("div", { class: "pp-actions", style: "justify-content:center;margin-top:16px" },
        request && h("button", { class: "nb-btn primary", type: "button", onclick: generate }, "Try again"),
        h("a", { class: "nb-btn", href: "#/prompt" }, "Back to prompts")))
    );
  }

  function projectView() {
    el.code = h("textarea", { class: "code", spellcheck: "false", "aria-label": "Code editor", autocapitalize: "off", wrap: "soft" });
    el.frame = h("iframe", { title: "Live preview", sandbox: `allow-scripts allow-modals allow-forms allow-popups${LOOPBACK.includes(location.hostname) ? " allow-same-origin" : ""}` });
    el.live = h("input", { class: "live-url", readonly: true, "aria-label": "Live site address", value: liveUrl || "Preparing your live link…", onfocus: () => el.live.select() });
    el.open = h("button", { class: "nb-btn primary", type: "button", disabled: !liveUrl, onclick: () => liveUrl && window.open(liveUrl, "_blank", "noopener") }, "Open in new tab ↗");
    el.copyLink = h("button", { class: "nb-btn", type: "button", disabled: !liveUrl, onclick: () => NW.copy(liveUrl, el.copyLink) }, "Copy link");
    el.tabs = h("div", { class: "tabs", role: "tablist", "aria-label": "Project files" },
      ...project.files.map((f) => h("button", { class: "tab", type: "button", role: "tab", "data-path": f.path, onclick: () => openFile(f.path) }, h("span", { class: `ext ${ext(f.path)}` }, ext(f.path)), f.path)));
    const copy = h("button", { class: "tab-copy", type: "button", onclick: () => NW.copy(el.code.value, copy) }, "Copy file");

    el.code.addEventListener("input", () => {
      fileOf(activePath).content = el.code.value;
      cache();
      clearTimeout(runTimer);
      runTimer = setTimeout(runPreview, 700); // the live site follows your edits
    });
    el.code.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      e.preventDefault(); // keep focus in the editor and indent instead
      const { selectionStart: s, selectionEnd: t, value } = el.code;
      el.code.value = `${value.slice(0, s)}  ${value.slice(t)}`;
      el.code.selectionStart = el.code.selectionEnd = s + 2;
      el.code.dispatchEvent(new Event("input"));
    });

    el.main = h("div", { class: "cp-main", "data-view": layout },
      h("div", { class: "editor" }, h("div", { class: "tabs-bar" }, el.tabs, copy), el.code),
      h("div", { class: "preview-pane" }, h("div", { class: "bar" }, h("span", {}, "Live preview"), h("button", { class: "tab-copy", type: "button", onclick: runPreview }, "Reload ↻")), el.frame)
    );
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Layout" },
      ...[["code", "Code"], ["split", "Split"], ["preview", "Preview"]].map(([v, label]) =>
        h("button", { type: "button", "data-v": v, "aria-pressed": String(v === layout), onclick: () => {
          layout = v;
          el.main.dataset.view = v;
          seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
        } }, label)));

    const zip = h("button", { class: "nb-btn", type: "button", onclick: async () => {
      zip.disabled = true;
      try { NW.saveBlob(await NW.fetchBlob("/api/zip", { files: project.files }), `${NW.slug(project.title)}.zip`); }
      catch (e) { alert(`Could not make the ZIP: ${e.message}`); }
      zip.disabled = false;
    } }, "Download ZIP");

    return shell(
      h("div", { class: "cp-top" },
        h("div", {}, h("h1", {}, project.title), h("p", { class: "lede" }, "Plain HTML, CSS and JavaScript. Edit any file and the live site updates."),
          h("div", { class: "pp-chips", style: "margin-top:10px" }, h("span", { class: "chip" }, `${project.files.length} files`), h("span", { class: "chip" }, "No build step"), project.saved && h("span", { class: "chip ok" }, "Saved"))),
        h("div", { class: "cp-actions" }, zip)
      ),
      h("div", { class: "live-bar" }, h("label", {}, "Live site"), el.live, el.open, el.copyLink, seg),
      el.main
    );
  }

  function render() {
    el = {};
    clearInterval(hintTimer);
    const page =
      status === "generating" ? generatingView() : status === "error" ? errorView() : status === "ready" && project ? projectView() : emptyView();
    view.replaceChildren(page);
    if (status === "ready" && project) {
      openFile(fileOf(activePath) ? activePath : project.files[0].path);
      runPreview();
    }
  }

  NW.pages.code = {
    async onShow() {
      if (status === "empty") {
        // A project from an earlier visit: this browser's cache first, then the database.
        const c = cached();
        if (c?.files?.length) project = c;
        else {
          try { project = (await NW.api(`/api/code?client_id=${NW.clientId}`)).project; } catch { /* database not ready: nothing to restore */ }
        }
        if (project?.files?.length) { status = "ready"; activePath = (project.files.find((f) => f.path === "index.html") || project.files[0]).path; }
      }
      render();
    },
  };
})();
