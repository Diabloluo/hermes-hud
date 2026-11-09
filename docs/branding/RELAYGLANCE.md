# 驿览 · RelayGlance

RelayGlance（中文名“驿览”）是 Hermes HUD 的新展示名，不是另一个插件，也不是 Hermes 官方产品。本次只调整 Web 插件、README 和当前入门文档的展示层。

## 保持兼容 / Compatibility

- Repository: `Diabloluo/hermes-hud`.
- Plugin ID and enabled configuration entry: `hermes-hud`.
- Page: `/hud`; API prefix: `/api/plugins/hermes-hud`; API schema: `1`.
- Plugin directory: `~/.hermes/plugins/hermes-hud`; local observation history: `~/.hermes/hud/`.
- `HERMES_HOME`, `HUD_*`, database fields and browser key `hermes-hud-locale` are unchanged.
- Desktop bundle ID: `com.diabloluo.hermes-hud-desktop`.

Existing installs need no data migration or directory rename. Follow the existing installation/upgrade procedure. Keep the established technical names in scripts, links, issue reports and configuration. Historical tags, release files and screenshots are not rewritten to appear newly branded.

## 图标 / Icon

`dashboard/dist/relayglance-radar.png` is the selected, unmodified 1254×1254 RGB radar artwork. SHA-256: `2b3cb47ffbfcb0570001c394d925ff8ba46452aa5a8905ee28462e6f97366277`.

The Web plugin displays it beside the page title. CSS uses a relative asset URL so the host's base-path and profile-scoped plugin asset routes are preserved. The image is served locally; it adds no third-party image request. The adjacent heading supplies the name; the decorative image is hidden from assistive technology.

Hermes 0.23's sidebar accepts a fixed set of icon names, not PNG paths. This change does not alter the host or promise a custom radar sidebar icon. Its existing `manifest.icon` is retained.

## Desktop 与发布边界 / Release boundary

The released **Desktop Alpha 0.1.0** app, DMG, Dock/tray icons and application name are unchanged. Do not describe this Web change as a new Desktop binary. A future Desktop rebrand requires separate icon production, versioning, replacement/launch tests, signing and notarization; keeping the Bundle ID alone is not sufficient.

Web branding is versioned separately as plugin v1.2.4, based on v1.2.3. The published v1.2.3 tag and files are not overwritten. Source code and a public release are not proof of a live deployment; check the installed instance separately.

## 定位 / Claims

An unofficial, local Hermes community dashboard. Core Hermes stores remain read-only; the plugin still maintains its own local observation database. Estimated costs are not provider bills. A new name or radar mark is not evidence of official affiliation, complete compatibility, automated repair or a security guarantee.

Name screening found no clear exact software conflict in the limited public search. It is not trademark clearance, domain registration or a guarantee of package-name availability.
