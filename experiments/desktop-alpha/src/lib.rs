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

/// 探测 Dashboard + 版本契约：
/// - GET /（200 = 服务存活）
/// - GET /health：401 = 服务在但需鉴权（正常态——native 不抓 token，
///   Auth Boundary）→ detected；200 = 公开 → 校验 api_schema_version /
///   plugin_version，不匹配 → 明确兼容性原因（fallback 屏展示）。
fn probe_dashboard() -> Result<Option<String>, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(2000))
        .build()
        .map_err(|e| format!("http client: {e}"))?;
    let root = client
        .get(format!("http://{DASHBOARD_HOST}:{}/", dashboard_port()))
        .send()
        .map_err(|e| format!("dashboard probe failed: {e}"))?;
    if !root.status().is_success() {
        return Ok(Some(format!("dashboard HTTP {}", root.status())));
    }
    // 版本契约（仅当 /health 公开可读；401 → 正常鉴权态，跳过检查）
    let health = client
        .get(format!("http://{DASHBOARD_HOST}:{}/api/plugins/hermes-hud/health", dashboard_port()))
        .send()
        .map_err(|e| format!("health probe failed: {e}"))?;
    if health.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Ok(None);  // 服务在（需鉴权）→ 导航 /hud，页面内鉴权
    }
    if health.status().is_success() {
        let body: serde_json::Value = health.json().map_err(|e| format!("health json: {e}"))?;
        let api = body.get("api_schema_version").and_then(|v| v.as_u64());
        let plugin = body.get("plugin_version").and_then(|v| v.as_str()).unwrap_or("");
        match api {
            Some(v) if v == EXPECTED_API_SCHEMA && plugin >= MIN_PLUGIN_VERSION => Ok(None),
            _ => Ok(Some(format!(
                "incompatible: api_schema_version={:?} plugin_version={:?} (expected {} / >= {})",
                api, plugin, EXPECTED_API_SCHEMA, MIN_PLUGIN_VERSION
            ))),
        }
    } else {
        Ok(Some(format!("health HTTP {}", health.status())))
    }
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

            // 启动探测：Dashboard 可达且兼容 → 导航到 /hud；否则留在 fallback
            let win = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(500));
                let reason = match probe_dashboard() {
                    Ok(None) => None,
                    Ok(Some(r)) => Some(r),
                    Err(e) => Some(e),
                };
                if let Some(r) = reason.clone() {
                    let _ = win.eval(format!(
                        "window.__hud_fallback_reason__ = {:?}; window.__hud_show_fallback__ && window.__hud_show_fallback__({:?});",
                        r, r
                    ));
                } else {
                    DETECTED.store(true, Ordering::Relaxed);
                    let _ = win.navigate(dashboard_url().parse().unwrap());
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
                        ("probe_reason", reason.clone().unwrap_or_else(|| "ok".into())),
                        ("api_schema_version", format!("{EXPECTED_API_SCHEMA}")),
                        ("min_plugin_version", MIN_PLUGIN_VERSION.into()),
                        ("remote_ipc_internals", ipc),
                        ("remote_tauri_global", tauri_global),
                        ("remote_host", host),
                        ("hud_page_loaded", has_hud),
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
}
