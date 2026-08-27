//! Hermes HUD — macOS Desktop Alpha v0.1.
//!
//! Productized Tauri shell over the running Hermes Dashboard.
//!
//! Security planes (Foundation freeze — MUST NOT REGRESS):
//! - remote HUD WebView (`http://127.0.0.1:<port>/hud`): ZERO Tauri
//!   capabilities (capabilities/local-bundled.json is `local: true` only —
//!   confined to bundled tauri:// pages); page talks to Dashboard via plain
//!   fetch/WebSocket/localStorage; navigation guard; page-context compat
//!   handshake; fail closed.
//! - local bundled fallback/setup page: ONE narrow operation,
//!   `start_dashboard`, gated in Rust by origin check (tauri:// allowed,
//!   http remote DENIED) and executing ONLY a fixed argv
//!   (<resolved-hermes> dashboard --host 127.0.0.1 --port <p> --no-open)
//!   via std::process::Command — no shell, no interpolation.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    webview::WebviewWindowBuilder,
    Manager, WebviewUrl,
};

const DASHBOARD_HOST: &str = "127.0.0.1";
const DEFAULT_PORT: u16 = 9119;
const MIN_PLUGIN_VERSION: &str = "1.1.0";
const START_TIMEOUT_S: u64 = 15;

/// 已知的用户级 hermes 可执行路径（确定性 discovery，不猜）。
const KNOWN_HERMES_PATHS: &[&str] = &[
    ".hermes/hermes-agent/venv/bin/hermes",
    ".cargo/bin/hermes",
    "/usr/local/bin/hermes",
    "/opt/homebrew/bin/hermes",
];

static DETECTED: AtomicBool = AtomicBool::new(false);

/// 恢复状态机（F）：每个状态有明确 UI，不允许 blank/endless spinner/silent failure。
#[derive(Clone, Debug, PartialEq)]
enum State {
    Detecting,
    Connected,
    DashboardNotRunning,
    StartingDashboard,
    Incompatible(String),
    HermesNotFound,
    ConnectionFailed(String),
}

fn state_id(s: &State) -> &'static str {
    match s {
        State::Detecting => "detecting",
        State::Connected => "connected",
        State::DashboardNotRunning => "dashboard-not-running",
        State::StartingDashboard => "starting-dashboard",
        State::Incompatible(_) => "incompatible",
        State::HermesNotFound => "hermes-not-found",
        State::ConnectionFailed(_) => "connection-failed",
    }
}

// ---------------------------------------------------------------------------
// Hermes binary discovery（C）：inherited PATH → known user-local paths →
// env override（test only）。禁止 shell -c / eval / 任意命令。
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Test-only overrides（B/DR-2）：HUD_HERMES_BIN / HUD_DESKTOP_TEST_HOME /
// HUD_DESKTOP_AUTOSTART / TEST_MODE 仅编译进 test / desktop-test-hooks build。
// Public release build 根本不含这些入口（编译期边界，非运行时门控）。
// ---------------------------------------------------------------------------
#[cfg(any(test, feature = "desktop-test-hooks"))]
fn test_mode() -> bool {
    std::env::var("HUD_DESKTOP_TEST_MODE").is_ok()
}

#[cfg(any(test, feature = "desktop-test-hooks"))]
fn hermes_home() -> Option<std::ffi::OsString> {
    if test_mode() {
        if let Some(h) = std::env::var_os("HUD_DESKTOP_TEST_HOME") {
            return Some(h);
        }
    }
    std::env::var_os("HOME")
}

// Public build：无 test hooks——HOME 恒真实
#[cfg(not(any(test, feature = "desktop-test-hooks")))]
fn hermes_home() -> Option<std::ffi::OsString> {
    std::env::var_os("HOME")
}

fn find_hermes() -> Option<PathBuf> {
    // env override（仅 test/desktop-test-hooks build 存在）
    #[cfg(any(test, feature = "desktop-test-hooks"))]
    {
        if test_mode() {
            if let Ok(b) = std::env::var("HUD_HERMES_BIN") {
                let p = PathBuf::from(&b);
                if p.exists() {
                    return Some(p);
                }
            }
        }
    }
    // inherited PATH
    if let Ok(path) = std::env::var("PATH") {
        for dir in path.split(':') {
            let cand = Path::new(dir).join("hermes");
            if cand.exists() {
                return Some(cand);
            }
        }
    }
    // known user-local paths（HUD_DESKTOP_TEST_HOME 仅 test build 生效）
    if let Some(home) = hermes_home() {
        for rel in KNOWN_HERMES_PATHS {
            let cand = Path::new(&home).join(rel);
            if cand.exists() {
                return Some(cand);
            }
        }
    }
    None
}

fn resolved_hermes_label() -> String {
    match find_hermes() {
        Some(p) => p
            .file_name()
            .map(|f| f.to_string_lossy().into_owned())
            .unwrap_or_else(|| "hermes".into()),
        None => "not-found".into(),
    }
}

// ---------------------------------------------------------------------------
// Port（H）：默认 9119；HUD_DASHBOARD_PORT（developer/test only）。1..65535。
// ---------------------------------------------------------------------------
fn dashboard_port() -> u16 {
    std::env::var("HUD_DASHBOARD_PORT")
        .ok()
        .and_then(|p| p.parse::<u16>().ok())
        .filter(|p| *p >= 1)
        .unwrap_or(DEFAULT_PORT)
}

fn dashboard_url() -> String {
    format!("http://{DASHBOARD_HOST}:{}/hud", dashboard_port())
}

fn dashboard_root_url() -> String {
    format!("http://{DASHBOARD_HOST}:{}/", dashboard_port())
}

// ---------------------------------------------------------------------------
// 兼容性判定（semver，单一实现）。
// ---------------------------------------------------------------------------
fn version_compat(api: Option<u64>, plugin: &str) -> Result<(), String> {
    if api != Some(1) {
        return Err(format!(
            "incompatible API schema: {:?} (expected 1)",
            api
        ));
    }
    let ver = semver::Version::parse(plugin).map_err(|e| {
        format!("malformed plugin_version {plugin:?}: {e} (expected >= {MIN_PLUGIN_VERSION})")
    })?;
    let min = semver::Version::parse(MIN_PLUGIN_VERSION).expect("MIN_PLUGIN_VERSION valid semver");
    if ver >= min {
        Ok(())
    } else {
        Err(format!(
            "incompatible plugin_version {plugin:?} (expected >= {MIN_PLUGIN_VERSION})"
        ))
    }
}

#[derive(Debug)]
enum Probe {
    Verified,
    AuthRequired,
    Incompatible(String),
}

fn probe_dashboard() -> Result<Probe, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(2000))
        .build()
        .map_err(|e| format!("http client: {e}"))?;
    let root = client
        .get(dashboard_root_url())
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
        return Ok(Probe::AuthRequired);
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

/// Page-context handshake：页面 auth 调 /health，仅版本值经 hash 回传（无 token）。
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
    location.hash = 'hud_compat=' + JSON.stringify({ api_schema_version: d.api_schema_version, plugin_version: d.plugin_version });
  } catch (e) {
    location.hash = 'hud_compat=' + 'unverified:' + encodeURIComponent(String(e && e.message || e).slice(0, 80));
  }
})();
"#;

fn read_handshake(win: &tauri::WebviewWindow) -> Option<String> {
    let frag = win
        .url()
        .ok()
        .and_then(|u| u.fragment().map(|f| f.to_string()))
        .unwrap_or_default();
    let val = frag.strip_prefix("hud_compat=")?;
    Some(val.to_string())
}

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

fn nav_allowed(url: &tauri::Url) -> bool {
    if url.scheme() == "tauri" {
        return true;
    }
    if url.scheme() == "http"
        || url.scheme() == "https"
        || url.scheme() == "ws"
        || url.scheme() == "wss"
    {
        let host = url.host_str().unwrap_or("");
        if host == "127.0.0.1" || host == "localhost" {
            return true;
        }
    }
    false
}

// ---------------------------------------------------------------------------
// 状态机驱动：探测 + handshake + 启动 Dashboard + 状态推送（fallback UI + tray）。
// ---------------------------------------------------------------------------
struct Machine {
    state: Mutex<State>,
    win: tauri::WebviewWindow,
}

fn push_state(m: &Machine, state: State) {
    {
        let mut cur = m.state.lock().unwrap();
        *cur = state.clone();
    }
    // 状态日志（test/desktop-test-hooks build 才写；public build 无此文件）
    #[cfg(any(test, feature = "desktop-test-hooks"))]
    {
        use std::io::Write as _;
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open("/tmp/hud-state.log")
        {
            let _ = writeln!(f, "{}", state_id(&state));
        }
    }
    let id = state_id(&state);
    let detail = match &state {
        State::Incompatible(r) => r.clone(),
        State::ConnectionFailed(r) => r.clone(),
        _ => String::new(),
    };
    let hermes = resolved_hermes_label();
    let _ = m.win.eval(&format!(
        "window.__hud_set_state__ && window.__hud_set_state__({:?}, {:?}, {:?});",
        id, detail, hermes
    ));
}

/// 探测一次并驱动状态（不含启动）。返回是否 Connected。
fn detect_once(m: &Machine) -> bool {
    let probe = match probe_dashboard() {
        Ok(p) => p,
        Err(e) => {
            // Dashboard 不可达：hermes 在 → DashboardNotRunning；否则 HermesNotFound
            if find_hermes().is_some() {
                push_state(m, State::DashboardNotRunning);
            } else {
                push_state(m, State::HermesNotFound);
            }
            #[cfg(any(test, feature = "desktop-test-hooks"))]
            let _ = std::fs::write("/tmp/hud-detect.log", format!("probe err: {e}\n"));
            return false;
        }
    };
    match probe {
        Probe::Verified => {
            DETECTED.store(true, Ordering::Relaxed);
            push_state(m, State::Connected);
            let _ = m.win.navigate(dashboard_url().parse().unwrap());
            true
        }
        Probe::AuthRequired => {
            // 导航 /hud → page-context handshake
            DETECTED.store(true, Ordering::Relaxed);
            let _ = m.win.navigate(dashboard_url().parse().unwrap());
            std::thread::sleep(Duration::from_secs(3));
            let _ = m.win.eval(HANDSHAKE_JS);
            let mut outcome = String::from("unverified:timeout");
            for _ in 0..16 {
                std::thread::sleep(Duration::from_millis(500));
                if let Some(v) = read_handshake(&m.win) {
                    if !v.is_empty() && v != "unverified:timeout" {
                        outcome = v;
                        break;
                    }
                }
            }
            if let Some(raw) = outcome.strip_prefix("unverified:") {
                let reason = format!("compatibility unverified: {raw}");
                #[cfg(any(test, feature = "desktop-test-hooks"))]
                let _ = std::fs::write("/tmp/hud-handshake.log", format!("{reason}\n"));
                go_fallback(m, State::ConnectionFailed(reason));
                false
            } else {
                let outcome = pct_decode(&outcome);
                #[cfg(any(test, feature = "desktop-test-hooks"))]
                let _ = std::fs::write("/tmp/hud-handshake.log", format!("payload: {outcome}\n"));
                let parsed: Option<(Option<u64>, String)> =
                    serde_json::from_str::<serde_json::Value>(&outcome)
                        .ok()
                        .and_then(|v| {
                            Some((
                                v.get("api_schema_version").and_then(|x| x.as_u64()),
                                v.get("plugin_version")
                                    .and_then(|x| x.as_str())
                                    .unwrap_or("")
                                    .to_string(),
                            ))
                        });
                match parsed {
                    Some((api, plugin)) => match version_compat(api, &plugin) {
                        Ok(()) => {
                            push_state(m, State::Connected);
                            true  // 留在 /hud（compatibility verified）
                        }
                        Err(e) => {
                            go_fallback(m, State::Incompatible(e));
                            false
                        }
                    },
                    None => {
                        go_fallback(
                            m,
                            State::ConnectionFailed(format!(
                                "compatibility unverified: bad handshake payload {outcome:?}"
                            )),
                        );
                        false
                    }
                }
            }
        }
        Probe::Incompatible(r) => {
            go_fallback(m, State::Incompatible(r));
            false
        }
    }
}

fn go_fallback(m: &Machine, state: State) {
    let _ = m.win.navigate("tauri://localhost/setup.html".parse().unwrap());
    std::thread::sleep(Duration::from_millis(800));  // 等页面加载
    push_state(m, state);
}

/// 启动 Dashboard（固定 argv，无 shell）——**probe-before-spawn**：
/// Command::new 之前立即再次 probe；Dashboard 已存在 → 不 spawn（Ok(None)），
/// 直接 connect/recover 现有实例（原子语义：spawn 前一刻才决定）。
/// 返回 Ok(Some(pid)) = 本进程启动；Ok(None) = 已存在未启动；Err = 失败。
fn maybe_spawn_dashboard() -> Result<Option<u32>, String> {
    match probe_dashboard() {
        Ok(Probe::Verified) | Ok(Probe::AuthRequired) => return Ok(None),
        _ => {}
    }
    let hermes = find_hermes().ok_or("Hermes Agent not found — cannot start Dashboard")?;
    let port = dashboard_port();
    let child = Command::new(&hermes)
        .args([
            "dashboard",
            "--host",
            DASHBOARD_HOST,
            "--port",
            &port.to_string(),
            "--no-open",
        ])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("failed to start dashboard: {e}"))?;
    Ok(Some(child.id()))
}

/// 启动 Dashboard + 15s poll（G：Start timeout 15s，禁止无限轮询）。
/// 由 start_dashboard command 与 HUD_DESKTOP_AUTOSTART 测试模式共用。
fn spawn_and_poll(m: Machine) {
    push_state(&m, State::StartingDashboard);
    std::thread::spawn(move || {
        let start = std::time::Instant::now();
        while start.elapsed() < Duration::from_secs(START_TIMEOUT_S) {
            std::thread::sleep(Duration::from_millis(1500));
            if detect_once(&m) {
                return;
            }
        }
        if !DETECTED.load(Ordering::Relaxed) {
            push_state(
                &m,
                State::ConnectionFailed(format!(
                    "Dashboard did not become ready within {START_TIMEOUT_S}s"
                )),
            );
        }
    });
}

/// 自定义 command：本地 bundled 页面（tauri://）唯一窄操作。
/// Origin 门控（机械证明）：remote http origin → DENIED。
#[tauri::command]
fn start_dashboard(window: tauri::WebviewWindow, app: tauri::AppHandle) -> Result<String, String> {
    let url = window.url().map_err(|e| format!("window url: {e}"))?;
    if url.scheme() != "tauri" {
        // remote /hud 页面 → DENIED（capability `local: true` 本已隔离，
        // Rust origin 检查是第二道机械证明）
        return Err("DENIED: start_dashboard is local-only (remote origin not allowed)".into());
    }
    if find_hermes().is_none() {
        return Err("Hermes Agent not found".into());
    }
    let spawned = maybe_spawn_dashboard()?;
    if spawned.is_none() {
        // Dashboard 已存在（probe-before-spawn 原子判定）→ 直接 connect
        let m = Machine {
            state: Mutex::new(State::Detecting),
            win: window.clone(),
        };
        push_state(&m, State::Detecting);
        std::thread::spawn(move || {
            detect_once(&m);
        });
        return Ok("dashboard already running — connected".into());
    }
    let m = Machine {
        state: Mutex::new(State::StartingDashboard),
        win: window.clone(),
    };
    spawn_and_poll(m);
    Ok(format!("started pid {}", spawned.unwrap()))
}

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // 第二实例启动 → focus 现有窗口（P：single-instance，不重复 tray/Dashboard）
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![start_dashboard])
        .setup(|app| {
            let window = WebviewWindowBuilder::new(
                app, "main", WebviewUrl::App("setup.html".into()),
            )
            .title("Hermes HUD")
            .inner_size(1280.0, 800.0)
            .on_navigation(|url| nav_allowed(url))
            .build()?;

            // —— Tray（I）：Open / Retry / Quit ——
            let open_i = MenuItem::with_id(app, "open", "Open Hermes HUD", true, None::<&str>)?;
            let retry_i = MenuItem::with_id(app, "retry", "Retry Connection", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open_i, &retry_i, &quit_i])?;
            // Tray 使用 Observer Core monochrome template mark（非彩色 App icon）
            let tray_icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray_template_20.png"))
                .map_err(|e| e.to_string())?;
            let mut tray_builder = TrayIconBuilder::with_id("hud-tray")
                .icon(tray_icon)
                .icon_as_template(true)  // macOS template image：明暗菜单栏自动适配
                .menu(&menu)
                .tooltip("Hermes HUD")
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
                    "retry" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let m = Machine {
                                state: Mutex::new(State::Detecting),
                                win: w.clone(),
                            };
                            push_state(&m, State::Detecting);
                            std::thread::spawn(move || {
                                if !detect_once(&m) {
                                    // 不自动循环（工单 G：手动 Retry，不无限轮询）
                                }
                            });
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            // —— 启动探测（一次；后续由 Retry / Start 驱动）——
            let win = window.clone();
            std::thread::spawn(move || {
                std::thread::sleep(Duration::from_millis(500));
                let _ = win.eval(&format!(
                    "window.__hud_retry_url__ = {:?};",
                    dashboard_url()
                ));
                let m = Machine {
                    state: Mutex::new(State::Detecting),
                    win: win.clone(),
                };
                push_state(&m, State::Detecting);
                if !detect_once(&m) {
                    // autostart fixture（B/DR-2）：仅 test/desktop-test-hooks build
                    #[cfg(any(test, feature = "desktop-test-hooks"))]
                    {
                        if test_mode()
                            && std::env::var("HUD_DESKTOP_AUTOSTART").is_ok()
                            && find_hermes().is_some()
                        {
                            if maybe_spawn_dashboard().ok().flatten().is_some() {
                                spawn_and_poll(m);
                            }
                        }
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
    let _ = app;
}

/// 导航守卫单元测试 + semver + discovery。
#[cfg(test)]
mod tests {
    use super::*;

    /// env 相关测试共享串行锁（cargo test 并行会互踩 HUD_* 环境变量）。
    static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    fn lock_env() -> std::sync::MutexGuard<'static, ()> {
        ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner())
    }

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
        assert!(nav_allowed(&u("tauri://localhost/setup.html")));
    }

    #[test]
    fn nav_guard_blocks_external_origins() {
        assert!(!nav_allowed(&u("https://example.com/")));
        assert!(!nav_allowed(&u("http://evil.example/x")));
        assert!(!nav_allowed(&u("file:///etc/passwd")));
        assert!(!nav_allowed(&u("javascript:alert(1)")));
        assert!(!nav_allowed(&u("data:text/html,<script>alert(1)</script>")));
    }

    #[test]
    fn semver_pass_cases() {
        for v in ["1.1.0", "1.1.1", "1.2.0", "2.0.0"] {
            assert!(version_compat(Some(1), v).is_ok(), "{v} should PASS");
        }
    }

    #[test]
    fn semver_fail_cases() {
        assert!(version_compat(Some(1), "1.0.9").is_err());
        assert!(version_compat(Some(1), "1.1.0-rc.1").is_err());
        assert!(version_compat(Some(0), "1.1.0").is_err());
        assert!(version_compat(None, "1.1.0").is_err());
    }

    #[test]
    fn semver_malformed_fail_closed() {
        for bad in ["", "not-a-version", "1.1", "v1.1.0", "1.1.0.0"] {
            assert!(version_compat(Some(1), bad).is_err(), "{bad:?} should FAIL CLOSED");
        }
    }

    #[test]
    fn port_validated_loopback_only() {
        let _g = lock_env();
        assert_eq!(dashboard_port(), 9119); // 默认
        // HUD_DASHBOARD_PORT 解析失败/越界 → 回退 9119
        std::env::set_var("HUD_DASHBOARD_PORT", "0");
        assert_eq!(dashboard_port(), 9119);
        std::env::set_var("HUD_DASHBOARD_PORT", "70000");
        assert_eq!(dashboard_port(), 9119);
        std::env::set_var("HUD_DASHBOARD_PORT", "9128");
        assert_eq!(dashboard_port(), 9128);
        std::env::remove_var("HUD_DASHBOARD_PORT");
    }

    #[test]
    fn start_argv_is_fixed_and_shell_free() {
        let _g = lock_env();
        // start_dashboard_bin 必须用固定 argv（无 shell、无插值）。
        // fake 二进制把 argv 写到文件 → 断言参数结构 + 拒绝注入。
        let fake = std::env::temp_dir().join("hud-fake-hermes");
        std::fs::write(
            &fake,
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > /tmp/hud-fake-argv.txt\nexit 0\n",
        )
        .unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        std::env::set_var("HUD_DESKTOP_TEST_MODE", "1");
        std::env::set_var("HUD_HERMES_BIN", &fake);
        std::env::set_var("HUD_DASHBOARD_PORT", "9494");  // 空端口 → probe 失败 → spawn
        let _ = std::fs::remove_file("/tmp/hud-fake-argv.txt");
        let pid = maybe_spawn_dashboard()
            .expect("start with fixed argv should work")
            .expect("should spawn (no dashboard at test port)");
        assert!(pid > 0);
        // 等 fake 脚本写完 argv 文件（spawn 异步）
        for _ in 0..20 {
            if std::path::Path::new("/tmp/hud-fake-argv.txt").exists() {
                break;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        // 固定 argv：dashboard --host 127.0.0.1 --port <p> --no-open（无注入/无 shell 元字符路径）
        let argv = std::fs::read_to_string("/tmp/hud-fake-argv.txt").unwrap_or_default();
        let parts: Vec<&str> = argv.split_whitespace().collect();
        assert_eq!(parts, vec!["dashboard", "--host", "127.0.0.1", "--port", "9494", "--no-open"]);
        std::env::remove_var("HUD_HERMES_BIN");
        std::env::remove_var("HUD_DESKTOP_TEST_MODE");
        std::env::remove_var("HUD_DASHBOARD_PORT");
        let _ = std::fs::remove_file("/tmp/hud-fake-argv.txt");
    }

    #[test]
    fn probe_before_spawn_no_duplicate() {
        let _g = lock_env();
        // state 显示 stopped → Start 前 Dashboard 变得可达 → spawn count = 0
        std::env::set_var("HUD_DESKTOP_TEST_MODE", "1");
        let fake = std::env::temp_dir().join("hud-fake-hermes2");
        std::fs::write(&fake, "#!/bin/sh\nexit 0\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        std::env::set_var("HUD_HERMES_BIN", &fake);
        // fake dashboard（root 200 + /health 401 → AuthRequired = 已存在）
        // 动态找空闲端口（避免残留服务器占用固定端口）
        let port = (9400u16..9600)
            .find(|p| std::net::TcpListener::bind(("127.0.0.1", *p)).is_ok())
            .unwrap_or(9996);
        let fake_src = format!(
            "import http.server\nclass H(http.server.BaseHTTPRequestHandler):\n def do_GET(self):\n  if self.path == '/':\n   self.send_response(200); self.end_headers(); self.wfile.write(b'ok')\n  else:\n   self.send_response(401); self.end_headers()\n def log_message(self, *a): pass\nhttp.server.HTTPServer(('127.0.0.1', {port}), H).serve_forever()"
        );
        let mut child = Command::new("python3")
            .args(["-c", &fake_src])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .spawn()
            .expect("fake dashboard");
        std::thread::sleep(Duration::from_millis(1200));
        std::env::set_var("HUD_DASHBOARD_PORT", port.to_string());
        let spawned = maybe_spawn_dashboard().expect("probe ok");
        assert!(spawned.is_none(), "Dashboard reachable → must NOT spawn (spawn count = 0)");
        assert!(!std::path::Path::new("/tmp/hud-fake-argv.txt").exists());
        let _ = child.kill();
        let _ = child.wait();
        std::env::remove_var("HUD_HERMES_BIN");
        std::env::remove_var("HUD_DESKTOP_TEST_MODE");
        std::env::remove_var("HUD_DASHBOARD_PORT");
    }

    #[test]
    fn override_ignored_without_test_mode() {
        let _g = lock_env();
        // release .app：无 TEST_MODE → HUD_HERMES_BIN / HUD_DESKTOP_TEST_HOME 忽略
        // （不依赖真实 hermes 存在——断言 override 路径未被返回即可，CI 兼容）
        std::env::remove_var("HUD_DESKTOP_TEST_MODE");
        let fake = std::env::temp_dir().join("hud-fake-hermes3");
        std::fs::write(&fake, "#!/bin/sh\nexit 0\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&fake, std::fs::Permissions::from_mode(0o755)).unwrap();
        }
        std::env::set_var("HUD_HERMES_BIN", &fake);
        std::env::set_var("HUD_DESKTOP_TEST_HOME", "/tmp/hermes-hud-empty-home");
        let old_path = std::env::var("PATH").unwrap_or_default();
        std::env::set_var("PATH", "");
        let found = find_hermes();
        assert!(
            found.as_ref() != Some(&fake),
            "release must ignore test overrides (fake HUD_HERMES_BIN must NOT win)"
        );
        std::env::set_var("PATH", &old_path);
        std::env::remove_var("HUD_HERMES_BIN");
        std::env::remove_var("HUD_DESKTOP_TEST_HOME");
    }

    #[test]
    fn hermes_not_found_fails_closed() {
        let _g = lock_env();
        // TEST_MODE + 不存在 override + PATH 空 + 隔离 HOME → 找不到 → Err
        std::env::set_var("HUD_DESKTOP_TEST_MODE", "1");
        std::env::set_var("HUD_HERMES_BIN", "/nonexistent/hermes");
        std::env::set_var("HUD_DASHBOARD_PORT", "9495");  // 空端口 → probe 失败 → 查 hermes
        let old_path = std::env::var("PATH").unwrap_or_default();
        std::env::set_var("PATH", "");
        std::env::set_var("HUD_DESKTOP_TEST_HOME", "/tmp/hermes-hud-empty-home");
        let r = maybe_spawn_dashboard();
        assert!(r.is_err(), "hermes not found must fail closed");
        std::env::set_var("PATH", &old_path);
        std::env::remove_var("HUD_HERMES_BIN");
        std::env::remove_var("HUD_DESKTOP_TEST_HOME");
        std::env::remove_var("HUD_DESKTOP_TEST_MODE");
        std::env::remove_var("HUD_DASHBOARD_PORT");
    }

    #[test]
    fn state_machine_has_no_blank_states() {
        // 每个状态必须映射到明确 id（UI 有对应文案）
        for s in [
            State::Detecting,
            State::Connected,
            State::DashboardNotRunning,
            State::StartingDashboard,
            State::Incompatible("x".into()),
            State::HermesNotFound,
            State::ConnectionFailed("y".into()),
        ] {
            let id = state_id(&s);
            assert!(!id.is_empty());
            assert!(matches!(
                id,
                "detecting" | "connected" | "dashboard-not-running"
                    | "starting-dashboard" | "incompatible"
                    | "hermes-not-found" | "connection-failed"
            ));
        }
    }
}
