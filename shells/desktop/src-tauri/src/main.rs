// 念匣桌面壳入口。
// 壳启动时拉起 nianxia-core sidecar（PyInstaller 单文件，FastAPI:7420），
// 壳退出时 kill。sidecar 经 bundle.externalBin 内嵌（binaries/nianxia-core-<triple>.exe）。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::os::windows::process::CommandExt;
use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct CoreChild(Mutex<Option<CommandChild>>);

/// 首启播种：把安装包内置的 L0 模型（resources/models/*.gguf）拷到数据目录。
/// 已存在同名同尺寸文件则跳过，避免每次启动拷 2GB。
fn seed_models(app: &tauri::App) {
    let res_dir = match app.path().resource_dir() {
        Ok(p) => p.join("models"),
        Err(_) => return,
    };
    if !res_dir.is_dir() {
        return; // 安装包未内置模型（如开发态），跳过
    }
    // 与 core config.py 同源：优先 NIANXIA_DATA_ROOT，否则 文档/念匣
    let data_root = std::env::var("NIANXIA_DATA_ROOT")
        .map(std::path::PathBuf::from)
        .ok()
        .or_else(|| app.path().document_dir().ok().map(|d| d.join("念匣")));
    let Some(data_root) = data_root else { return };
    let dest_dir = data_root.join("models");
    if std::fs::create_dir_all(&dest_dir).is_err() {
        return;
    }
    let Ok(entries) = std::fs::read_dir(&res_dir) else { return };
    for e in entries.flatten() {
        let src = e.path();
        if src.extension().and_then(|s| s.to_str()) != Some("gguf") {
            continue;
        }
        let dest = dest_dir.join(e.file_name());
        let src_len = src.metadata().map(|m| m.len()).unwrap_or(0);
        let dest_len = dest.metadata().map(|m| m.len()).unwrap_or(0);
        if dest_len != src_len {
            if let Err(err) = std::fs::copy(&src, &dest) {
                eprintln!("[nianxia] seed model {:?} failed: {err}", e.file_name());
            }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(CoreChild(Mutex::new(None)))
        .setup(|app| {
            // dev 模式（npm run tauri:dev）下 core 由开发者手动起，不重复拉起
            if cfg!(debug_assertions) {
                return Ok(());
            }
            seed_models(app);
            match app.shell().sidecar("nianxia-core") {
                Ok(cmd) => match cmd.spawn() {
                    Ok((mut rx, child)) => {
                        app.state::<CoreChild>().0.lock().unwrap().replace(child);
                        tauri::async_runtime::spawn(async move {
                            while let Some(ev) = rx.recv().await {
                                if let CommandEvent::Terminated(t) = ev {
                                    eprintln!("[nianxia] core sidecar exited: {:?}", t.code);
                                }
                            }
                        });
                    }
                    Err(e) => eprintln!("[nianxia] core sidecar spawn failed: {e}"),
                },
                Err(e) => eprintln!("[nianxia] core sidecar resolve failed: {e}"),
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(child) = window.app_handle().state::<CoreChild>().0.lock().unwrap().take() {
                    // PyInstaller onefile 是 引导进程→实际进程 两级：child.kill() 只杀引导层，
                    // 必须 taskkill /T 杀整棵进程树，否则 core 成孤儿残留。
                    let _ = std::process::Command::new("taskkill")
                        .args(["/T", "/F", "/PID", &child.pid().to_string()])
                        .creation_flags(0x08000000) // CREATE_NO_WINDOW
                        .output();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running 念匣 desktop shell");
}
