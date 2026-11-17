// Tauri 2 入口：把 web/ 的构建产物装进原生窗口。
// 构建前需要 Rust 工具链（rustup）+ WebView2（Windows 自带）。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // 连接 http:// 内网地址时：Android 需要在 capacitor/tauri 配置里显式开 cleartext，
    // 桌面端默认允许；生产建议走 https（见 docs/DEPLOY.md）。
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .run(tauri::generate_context!())
        .expect("error while running study bridge");
}
