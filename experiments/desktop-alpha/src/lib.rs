//! Hermes HUD Desktop prototype — remote WebView shell.
//!
//! Security invariant (Desktop Foundation v0.1):
//! - The remote HUD WebView (`http://127.0.0.1:<port>/hud`) gets ZERO Tauri
//!   capabilities: no IPC, no shell, no fs, no dialog, no updater, no native
//!   commands (capabilities/default.json is an empty permission set).
//! - The page talks to the Dashboard exactly like a normal browser: fetch /
//!   WebSocket / localStorage.
//! - The native shell exposes no command bridge to remote content.
//! - Navigation guard: only 127.0.0.1 / localhost / tauri:// are allowed.

use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    webview::WebviewWindowBuilder,
    Manager, WebviewUrl,
};

const DASHBOARD_HOST: &str = "127.0.0.1";

fn dashboard_port() -> u16 {
    std::env::var("HUD_DASHBOARD_PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(9119)
}

fn dashboard_url() -> String {
    format!("http://{DASHBOARD_HOST}:{}/hud", dashboard_port())
}

const EXPECTED_API_SCHEMA: u64 = 1;
const MIN_PLUGIN_VERSION: &str = "1.1.0";

static DETECTED: AtomicBool = AtomicBool::new(false);

/// 导航守卫逻辑（独立函数便于单测 + smoke 断言）。
fn nav_allowed(url: &tauri::Url) -> bool {
    if url.scheme() == "tauri" {
        return true;
    }
    if url.scheme() == "http" || url.scheme() == "https"
        || url.scheme() == "ws" || url.scheme() == "wss" {
        let host = url.host_str().unwrap_or("");
        if host == "127.0.0.1" || host == "localhost" {
            return true;
        }
    }
    false
}

fn smoke_report(path: &str, lines: &[(&str, String)]) {
    let body = lines
        .iter()
        .map(|(k, v)| format!("  \"{k}\": \"{}\"", v.replace('"', "\\\"")))
        .collect::<Vec<_>>()
        .join(",\n");
    let _ = std::fs::write(path, format!("{{\n{body}\n}}\n"));
}

/// 兼容性判定（semver crate，单一实现——Rust 侧；页面 JS 只回传原始值）。
fn version_compat(api: Option<u64>, plugin: &str) -> Result<(), String> {
    if api != Some(EXPECTED_API_SCHEMA) {
        return Err(format!(
            "incompatible API schema: {:?} (expected {EXPECTED_API_SCHEMA})",
            api
        ));
    }
    let ver = semver::Version::parse(plugin).map_err(|e| {
        format!("malformed plugin_version {plugin:?}: {e} (expected >= {MIN_PLUGIN_VERSION})")
    })?;
    let min = semver::Version::parse(MIN_PLUGIN_VERSION).expect("MIN_PLUGIN_VERSION is valid semver");
    if ver >= min {
        Ok(())
    } else {
        Err(format!(
            "incompatible plugin_version {plugin:?} (expected >= {MIN_PLUGIN_VERSION})"
        ))
    }
}

/// 探测结果三态：
/// - Verified：/health 公开可读且版本匹配
/// - AuthRequired：root 存活但 /health 401（需页面上下文 handshake）
/// - Incompatible(reason)：公开但版本不匹配 / 其他失败 → fallback
enum Probe {
    Verified,
    AuthRequired,
    Incompatible(String),
}

/// 探测 Dashboard：GET /（200 = 服务存活）；GET /health：
/// - 401 = auth-required / compatibility-unverified（NOT compatibility OK）→
///   导航 /hud 后由 page-context handshake 验证（工单 3）
/// - 200 = 公开 → semver 版本校验
fn probe_dashboard() -> Result<Probe, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(2000))
        .build()
        .map_err(|e| format!("http client: {e}"))?;
    let root = client
        .get(format!("http://{DASHBOARD_HOST}:{}/", dashboard_port()))
        .send()
        .map_err(|e| format!("dashboard probe failed: {e}"))?;
    if !root.status().is_success() {
        return Ok(Probe::Incompatible(format!("dashboard HTTP {}", root.status())));
    }
    let health = client
        .get(format!(
            "http://{DASHBOARD_HOST}:{}/api/plugins/hermes-hud/health",
            dashboard_port()
        ))
        .send()
        .map_err(|e| format!("health probe failed: {e}"))?;
    if health.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Ok(Probe::AuthRequired);  // auth-required / compatibility-unverified
    }
    if health.status().is_success() {
        let body: serde_json::Value = health.json().map_err(|e| format!("health json: {e}"))?;
        let api = body.get("api_schema_version").and_then(|v| v.as_u64());
        let plugin = body.get("plugin_version").and_then(|v| v.as_str()).unwrap_or("");
        match version_compat(api, plugin) {
            Ok(()) => Ok(Probe::Verified),
            Err(e) => Ok(Probe::Incompatible(e)),
        }
    } else {
        Ok(Probe::Incompatible(format!("health HTTP {}", health.status())))
    }
}

/// Page-context handshake：注入只做版本检查的 JS（在页面上下文用现有
/// Dashboard auth 机制调 /health）。token 不离开页面、不回传 Rust、不写盘。
/// 结果（仅 api_schema_version + plugin_version 原始值）经 location.hash 回传。
const HANDSHAKE_JS: &str = r#"
(async () => {
  try {
    const SDK = window.__HERMES_PLUGIN_SDK__;
    const url = '/api/plugins/hermes-hud/health';
    let d;
    if (SDK && SDK.fetchJSON) { d = await SDK.fetchJSON(url); }
    else {
      d = await fetch(url, { headers: { 'X-Hermes-Session-Token': (window.__HERMES_SESSION_TOKEN__ || '') } });
      d = await d.json();
    }
    // 成功：紧凑 JSON（无 #/空格）——Rust 直接解析；token 绝不外传
    location.hash = 'hud_compat=' + JSON.stringify({ api_schema_version: d.api_schema_version, plugin_version: d.plugin_version });
  } catch (e) {
    location.hash = 'hud_compat=' + 'unverified:' + encodeURIComponent(String(e && e.message || e).slice(0, 80));
  }
})();
"#;

/// 读取 handshake 结果（location.hash → 原始版本值）。
fn read_handshake(win: &tauri::WebviewWindow) -> Option<String> {
    let frag = win
        .url()
        .ok()
        .and_then(|u| u.fragment().map(|f| f.to_string()))
        .unwrap_or_default();
    let val = frag.strip_prefix("hud_compat=")?;
    Some(val.to_string())
}

/// 简单 percent-decode（fragment() 返回 URL 编码——handshake JSON 需解码）。
fn pct_decode(s: &str) -> String {
    fn hex(b: u8) -> Option<u8> {
        match b {
            b'0'..=b'9' => Some(b - b'0'),
            b'a'..=b'f' => Some(b - b'a' + 10),
            b'A'..=b'F' => Some(b - b'A' + 10),
            _ => None,
        }
    }
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let (Some(h), Some(l)) = (hex(bytes[i + 1]), hex(bytes[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// smoke 模式：把 JS 表达式结果写入 location.hash，Rust 读回断言。
/// （不用 encodeURIComponent——url crate 的 fragment() 自动解码；
/// 仅转义 '#' 避免截断。）
fn js_probe(win: &tauri::WebviewWindow, js: &str) -> String {
    let _ = win.eval(&format!(
        "try {{ location.hash = 'r=' + String({js}).replace(/#/g, '%23'); }} catch(e) {{ location.hash = 'r=' + 'JSERR:' + String(e.message).replace(/#/g, '%23'); }}"
    ));
    std::thread::sleep(Duration::from_millis(500));
    win.url()
        .ok()
        .and_then(|u| u.fragment().map(|f| f.to_string()))
        .unwrap_or_default()
        .trim_start_matches("r=")
        .to_string()
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            // —— 手动建窗口（on_navigation 在此挂载）：初始 = bundled fallback ——
            let window = WebviewWindowBuilder::new(
                app, "main", WebviewUrl::App("fallback.html".into()),
            )
            .title("Hermes HUD")
            .inner_size(1280.0, 800.0)
            .on_navigation(|url| nav_allowed(url))
            .build()?;

            // 启动探测：三态决定 → Verified/AuthRequired 导航 /hud（后者随后
            // page-context handshake）；Incompatible/Err → fallback（fail closed）
            let win = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(500));
                // 注入 fallback 实际 dashboard URL（Retry 用当前端口，非硬编码）
                let _ = win.eval(&format!(
                    "window.__hud_retry_url__ = {:?};",
                    dashboard_url()
                ));
                let probe = match probe_dashboard() {
                    Ok(p) => p,
                    Err(e) => Probe::Incompatible(e),
                };
                let probe_summary = match &probe {
                    Probe::Verified => "ok".to_string(),
                    Probe::AuthRequired => "auth-required / compatibility-unverified".to_string(),
                    Probe::Incompatible(r) => r.clone(),
                };
                match probe {
                    Probe::Verified => {
                        DETECTED.store(true, Ordering::Relaxed);
                        let _ = win.navigate(dashboard_url().parse().unwrap());
                    }
                    Probe::AuthRequired => {
                        // auth-required / compatibility-unverified：导航 /hud，
                        // 页面加载后 page-context handshake 验证（工单 3）
                        DETECTED.store(true, Ordering::Relaxed);
                        let _ = win.navigate(dashboard_url().parse().unwrap());
                        std::thread::sleep(Duration::from_secs(3));  // 等页面 + SDK 注入
                        let _ = win.eval(HANDSHAKE_JS);
                        // 轮询 handshake 结果（最长 ~8s；超时 = unverified → fail closed）
                        let mut outcome = String::from("unverified:timeout");
                        for _ in 0..16 {
                            std::thread::sleep(Duration::from_millis(500));
                            if let Some(v) = read_handshake(&win) {
                                if !v.is_empty() && v != "unverified:timeout" {
                                    outcome = v;
                                    break;
                                }
                            }
                        }
                        if let Some(raw) = outcome.strip_prefix("unverified:") {
                            let _ = std::fs::write("/tmp/hud-handshake.log", format!("unverified: {raw}\n"));
                            // 检查本身失败 → fail closed → fallback
                            let _ = win.navigate(
                                "tauri://localhost/fallback.html".parse().unwrap(),
                            );
                            let _ = win.eval(&format!(
                                "window.__hud_fallback_reason__ = {:?}; window.__hud_show_fallback__ && window.__hud_show_fallback__({:?});",
                                format!("compatibility unverified: {raw}"), format!("compatibility unverified: {raw}")
                            ));
                        } else {
                            let outcome = pct_decode(&outcome);  // fragment 是 URL 编码
                            let _ = std::fs::write("/tmp/hud-handshake.log", format!("payload: {outcome}\n"));
                            // raw JSON {api_schema_version, plugin_version} → semver 判定
                            let parsed: Option<(Option<u64>, String)> = serde_json::from_str::<serde_json::Value>(&outcome)
                                .ok()
                                .and_then(|v| Some((
                                    v.get("api_schema_version").and_then(|x| x.as_u64()),
                                    v.get("plugin_version").and_then(|x| x.as_str()).unwrap_or("").to_string(),
                                )));
                            match parsed {
                                Some((api, plugin)) => match version_compat(api, &plugin) {
                                    Ok(()) => { /* compatibility_verified — 留在 /hud */ }
                                    Err(e) => {
                                        let _ = win.navigate("tauri://localhost/fallback.html".parse().unwrap());
                                        let _ = win.eval(&format!(
                                            "window.__hud_fallback_reason__ = {:?}; window.__hud_show_fallback__ && window.__hud_show_fallback__({:?});",
                                            e, e
                                        ));
                                    }
                                },
                                None => {
                                    let _ = win.navigate("tauri://localhost/fallback.html".parse().unwrap());
                                    let _ = win.eval(&format!(
                                        "window.__hud_fallback_reason__ = {:?}; window.__hud_show_fallback__ && window.__hud_show_fallback__({:?});",
                                        format!("compatibility unverified: bad handshake payload {outcome:?}"), format!("compatibility unverified: bad handshake payload")
                                    ));
                                }
                            }
                        }
                    }
                    Probe::Incompatible(r) => {
                        let _ = win.eval(&format!(
                            "window.__hud_fallback_reason__ = {:?}; window.__hud_show_fallback__ && window.__hud_show_fallback__({:?});",
                            r, r
                        ));
                    }
                }
                // —— smoke 模式（HUD_DESKTOP_SMOKE=1）：自动验证 + 报告 + 退出 ——
                if std::env::var("HUD_DESKTOP_SMOKE").is_ok() {
                    let _ = win.show();
                    let _ = win.set_focus();
                    std::thread::sleep(Duration::from_secs(6)); // 等页面加载
                    let t0 = std::time::Instant::now();
                    let ipc = js_probe(&win, "typeof window.__TAURI_INTERNALS__");
                    let tauri_global = js_probe(&win, "typeof window.__TAURI__");
                    let host = js_probe(&win, "location.host");
                    let has_hud = js_probe(
                        &win,
                        "!!(document.querySelector('.hud-tab') || document.body.textContent.includes('指挥中心'))",
                    );
                    // 诊断：SDK/token/fallback reason（handshake 路径证据）
                    let sdk_present = js_probe(&win, "typeof window.__HERMES_PLUGIN_SDK__");
                    let token_present = js_probe(
                        &win,
                        "!!(window.__HERMES_SESSION_TOKEN__ || (window.__HERMES_PLUGIN_SDK__ && window.__HERMES_PLUGIN_SDK__.__token__))",
                    );
                    let fallback_reason = js_probe(
                        &win,
                        "String(window.__hud_fallback_reason__ || '')",
                    );
                    // 功能 Tab 渲染证据（JS 内 textContent 检查——无编码问题）
                    let tab_timeline = js_probe(
                        &win,
                        "[...document.querySelectorAll('.hud-tab')].some(b => (b.textContent||'').includes('时间线'))",
                    );
                    let tab_skill_analytics = js_probe(
                        &win,
                        "[...document.querySelectorAll('.hud-tab')].some(b => (b.textContent||'').includes('技能分析'))",
                    );
                    let tab_cost = js_probe(
                        &win,
                        "[...document.querySelectorAll('.hud-tab')].some(b => (b.textContent||'').includes('费用'))",
                    );
                    // 尝试 invoke（remote 页面：bridge 存在但 capability 空 →
                    // 调用必须被拒。测两类：A) runtime 明确存在的 core command
                    // (plugin:window|get_all_windows)；B) 高风险 shell（未注册 →
                    // command not found，单独标注）。async await 等 2.5s）
                    let _ = win.eval(
                        "(window.__TAURI_INTERNALS__ ? (async () => { const out = {}; try { await window.__TAURI_INTERNALS__.invoke('plugin:window|get_all_windows'); out.core = 'ALLOWED'; } catch (e) { out.core = 'DENIED:' + String(e && e.message || e).slice(0, 80); } try { await window.__TAURI_INTERNALS__.invoke('shell:execute'); out.shell = 'ALLOWED'; } catch (e) { out.shell = 'DENIED:' + String(e && e.message || e).slice(0, 80); } location.hash = 'r=' + JSON.stringify(out).replace(/#/g, '%23'); })() : (location.hash = 'r=' + 'no-internals'))",
                    );
                    std::thread::sleep(Duration::from_millis(2500));
                    let invoke_try = win
                        .url()
                        .ok()
                        .and_then(|u| u.fragment().map(|f| f.to_string()))
                        .unwrap_or_default()
                        .trim_start_matches("r=")
                        .to_string();
                    // 导航守卫：尝试跳转外部域 → 应被阻止（host 不变）
                    let _ = win.eval("location.href='https://example.com/'");
                    std::thread::sleep(Duration::from_millis(1200));
                    let host_after = js_probe(&win, "location.host");
                    let guard_ok = host_after == host;
                    let first_render_ms = t0.elapsed().as_millis();
                    let rows: Vec<(&str, String)> = vec![
                        ("detected", DETECTED.load(Ordering::Relaxed).to_string()),
                        ("probe_reason", probe_summary),
                        ("api_schema_version", format!("{EXPECTED_API_SCHEMA}")),
                        ("min_plugin_version", MIN_PLUGIN_VERSION.into()),
                        ("remote_ipc_internals", ipc),
                        ("remote_tauri_global", tauri_global),
                        ("remote_host", host),
                        ("hud_page_loaded", has_hud),
                        ("sdk_present", sdk_present),
                        ("token_present", token_present),
                        ("fallback_reason", fallback_reason),
                        ("tab_timeline_rendered", tab_timeline.to_string()),
                        ("tab_skill_analytics_rendered", tab_skill_analytics.to_string()),
                        ("tab_cost_intelligence_rendered", tab_cost.to_string()),
                        ("invoke_attempt", invoke_try),
                        ("nav_guard_external_blocked", guard_ok.to_string()),
                        ("first_hud_render_ms", first_render_ms.to_string()),
                    ];
                    smoke_report("/tmp/hud-desktop-smoke.json", &rows);
                    let _ = std::fs::write("/tmp/hud-desktop-smoke.done", "1");
                    std::thread::sleep(Duration::from_millis(400));
                    let _ = win.eval("document.title = 'SMOKE_COMPLETE'");
                    std::thread::sleep(Duration::from_millis(400));
                    std::process::exit(0);
                }
            });

            // —— Tray：Open Hermes HUD / Quit ——
            let open_i = MenuItem::with_id(app, "open", "Open Hermes HUD", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_i, &quit_i])?;
            let mut tray_builder = TrayIconBuilder::with_id("hud-tray")
                .menu(&menu)
                .show_menu_on_left_click(false);
            if let Some(icon) = app.default_window_icon().cloned() {
                tray_builder = tray_builder.icon(icon);
            }
            let _tray = tray_builder
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "open" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // 关窗不退出（tray 驻留）；Quit 才退出
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// 导航守卫单元测试（navigation guard 逻辑真实验证）。
#[cfg(test)]
mod tests {
    use super::*;

    fn u(s: &str) -> tauri::Url {
        s.parse().unwrap()
    }

    #[test]
    fn nav_guard_allows_loopback() {
        assert!(nav_allowed(&u("http://127.0.0.1:9119/hud")));
        assert!(nav_allowed(&u("http://localhost:9119/hud")));
        assert!(nav_allowed(&u("ws://127.0.0.1:9119/events")));
    }

    #[test]
    fn nav_guard_allows_tauri_protocol() {
        assert!(nav_allowed(&u("tauri://localhost/fallback.html")));
    }

    #[test]
    fn nav_guard_blocks_external_origins() {
        assert!(!nav_allowed(&u("https://example.com/")));
        assert!(!nav_allowed(&u("http://evil.example/x")));
        assert!(!nav_allowed(&u("file:///etc/passwd")));
        assert!(!nav_allowed(&u("javascript:alert(1)")));
        assert!(!nav_allowed(&u("data:text/html,<script>alert(1)</script>")));
    }

    // —— semver 兼容性判定（工单 5：标准 semver，非字符串比较）——
    #[test]
    fn semver_pass_cases() {
        for v in ["1.1.0", "1.1.1", "1.2.0", "2.0.0"] {
            assert!(version_compat(Some(1), v).is_ok(), "{v} should PASS");
        }
    }

    #[test]
    fn semver_fail_cases() {
        assert!(version_compat(Some(1), "1.0.9").is_err());
        assert!(version_compat(Some(1), "1.1.0-rc.1").is_err());  // pre-release < 1.1.0
        assert!(version_compat(Some(0), "1.1.0").is_err());       // schema mismatch
        assert!(version_compat(None, "1.1.0").is_err());
    }

    #[test]
    fn semver_malformed_fail_closed() {
        // malformed → FAIL CLOSED（不 panic、返回 Err）
        for bad in ["", "not-a-version", "1.1", "v1.1.0", "1.1.0.0"] {
            assert!(version_compat(Some(1), bad).is_err(), "{bad:?} should FAIL CLOSED");
        }
    }
}
