use std::{
    path::{Path, PathBuf},
    process::Stdio,
    time::Duration,
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    process::Command,
    time::timeout,
};

use crate::Decision;

pub(crate) fn valid_id(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 32
        && id
            .bytes()
            .next()
            .is_some_and(|first| first.is_ascii_lowercase())
        && id
            .bytes()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == b'-')
}

fn executable(id: &str) -> PathBuf {
    match id {
        "codex" | "agy" => Path::new("/usr/local/lib/artemis-bridge/adapters").join(id),
        _ => Path::new("/providers").join(id),
    }
}

fn configured(id: &str) -> bool {
    use std::os::unix::fs::PermissionsExt;
    let path = match id {
        "codex" => PathBuf::from("/cli/codex/codex"),
        "agy" => PathBuf::from("/cli/agy/agy"),
        _ => executable(id),
    };
    path.metadata()
        .is_ok_and(|entry| entry.is_file() && entry.permissions().mode() & 0o111 != 0)
}

pub(crate) fn installed() -> Vec<String> {
    let mut ids: Vec<_> = std::fs::read_dir("/providers")
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|entry| entry.file_name().into_string().ok())
        .filter(|id| valid_id(id) && id != "codex" && id != "agy" && configured(id))
        .collect();
    ids.extend(
        ["codex", "agy"]
            .into_iter()
            .filter(|id| configured(id))
            .map(String::from),
    );
    ids.sort();
    ids
}

pub(crate) async fn invoke(id: &str, prompt: &str) -> Result<Decision, &'static str> {
    if !configured(id) {
        return Err("executable unavailable");
    }
    let mut command = Command::new(executable(id));
    command
        .current_dir("/tmp")
        .env_clear()
        .env("PATH", "/usr/local/bin:/usr/bin:/bin")
        .env("HOME", "/state")
        .env("TMPDIR", "/tmp")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .process_group(0)
        .kill_on_drop(true);
    let mut child = command.spawn().map_err(|_| "executable unavailable")?;
    let mut stdin = child.stdin.take().ok_or("missing stdin")?;
    let stdout = child.stdout.take().ok_or("missing stdout")?;
    let mut input = serde_json::to_vec(&serde_json::json!({"prompt": prompt}))
        .map_err(|_| "invalid request")?;
    input.push(b'\n');
    let pid = child.id();
    let output = timeout(Duration::from_secs(50), async {
        let mut bytes = Vec::new();
        let write = async move { stdin.write_all(&input).await };
        let mut bounded = stdout.take(65537);
        let read = bounded.read_to_end(&mut bytes);
        tokio::try_join!(write, read).map_err(|_| "CLI I/O error")?;
        if bytes.len() > 65536 {
            return Err("CLI output too large");
        }
        let status = child.wait().await.map_err(|_| "CLI wait failed")?;
        if !status.success() {
            return Err("CLI exited unsuccessfully");
        }
        Ok(bytes)
    })
    .await;
    if !matches!(output, Ok(Ok(_))) {
        if let Some(pid) = pid {
            use nix::{
                sys::signal::{killpg, Signal},
                unistd::Pid,
            };
            let _ = killpg(Pid::from_raw(pid as i32), Signal::SIGKILL);
        }
        let _ = child.wait().await;
    }
    let output = output.map_err(|_| "CLI timed out")??;
    serde_json::from_slice(&output).map_err(|_| "CLI returned invalid JSON")
}
