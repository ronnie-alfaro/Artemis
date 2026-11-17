mod providers;

use std::{
    collections::{HashMap, HashSet},
    sync::Arc,
    time::{Duration, Instant},
};

use axum::{
    extract::{DefaultBodyLimit, State},
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::{Mutex, Semaphore};

#[derive(Clone)]
struct Bridge {
    cooldown: Arc<Mutex<HashMap<String, Instant>>>,
    slots: Arc<Semaphore>,
    verified: Arc<Mutex<HashSet<String>>>,
}

#[derive(Deserialize)]
struct Turn {
    providers: Vec<String>,
    prompt: String,
    capabilities: Vec<String>,
    actions_remaining: u8,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Decision {
    reply: String,
    capability: String,
    command: String,
}

impl Decision {
    fn valid_for(&self, turn: &Turn) -> bool {
        if self.capability.is_empty() {
            return !self.reply.trim().is_empty()
                && self.reply.len() <= 24000
                && self.command.is_empty();
        }
        turn.actions_remaining > 0
            && turn.capabilities.contains(&self.capability)
            && !self.command.trim().is_empty()
            && self.command.len() <= 20000
    }
}

#[derive(Default, Serialize)]
struct Outcome {
    provider: Option<String>,
    decision: Option<Decision>,
}

async fn decide(State(bridge): State<Bridge>, Json(turn): Json<Turn>) -> Json<Outcome> {
    let Ok(slot) = bridge.slots.clone().try_acquire_owned() else {
        return Json(Outcome::default());
    };
    // Complete cleanup even when the caller disconnects during a CLI invocation.
    let outcome = tokio::spawn(async move {
        let _slot = slot;
        dispatch(bridge, turn).await
    })
    .await
    .unwrap_or_default();
    Json(outcome)
}

async fn dispatch(bridge: Bridge, turn: Turn) -> Outcome {
    for provider in turn.providers.iter().take(8) {
        if !providers::valid_id(provider) {
            continue;
        }
        if bridge
            .cooldown
            .lock()
            .await
            .get(provider)
            .is_some_and(|until| *until > Instant::now())
        {
            continue;
        }
        match providers::invoke(provider, &turn.prompt).await {
            Ok(decision) if decision.valid_for(&turn) => {
                bridge.cooldown.lock().await.remove(provider);
                bridge.verified.lock().await.insert(provider.clone());
                return Outcome {
                    provider: Some(provider.clone()),
                    decision: Some(decision),
                };
            }
            result => {
                let reason = result.err().unwrap_or("invalid decision");
                tracing::warn!(%provider, %reason, "provider failed");
                bridge.verified.lock().await.remove(provider);
                let mut cooldown = bridge.cooldown.lock().await;
                cooldown.retain(|_, until| *until > Instant::now());
                cooldown.insert(provider.clone(), Instant::now() + Duration::from_secs(20));
            }
        }
    }
    Outcome::default()
}

async fn status(State(bridge): State<Bridge>) -> Json<Value> {
    let cooldown = bridge.cooldown.lock().await;
    let verified = bridge.verified.lock().await;
    let providers = providers::installed()
        .into_iter()
        .map(|id| {
            let cooling_down = cooldown
                .get(&id)
                .is_some_and(|until| *until > Instant::now());
            let status = if cooling_down {
                "cooldown"
            } else if verified.contains(&id) {
                "ready"
            } else {
                "untested"
            };
            serde_json::json!({"id": id, "status": status})
        })
        .collect::<Vec<_>>();
    Json(serde_json::json!({"providers": providers}))
}

#[tokio::main]
async fn main() -> std::io::Result<()> {
    tracing_subscriber::fmt().init();
    let app = Router::new()
        .route("/healthz", get(|| async { "ok" }))
        .route("/v1/decide", post(decide))
        .route("/v1/providers", get(status))
        .layer(DefaultBodyLimit::max(512 * 1024))
        .with_state(Bridge {
            cooldown: Arc::default(),
            verified: Arc::default(),
            slots: Arc::new(Semaphore::new(4)),
        });
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8091").await?;
    axum::serve(listener, app).await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_unassigned_or_excessive_actions() {
        let mut turn = Turn {
            providers: vec![],
            prompt: String::new(),
            capabilities: vec!["seerr.media".into()],
            actions_remaining: 1,
        };
        let decision = Decision {
            reply: String::new(),
            capability: "seerr.media".into(),
            command: "buscar Matrix".into(),
        };
        assert!(decision.valid_for(&turn));
        turn.actions_remaining = 0;
        assert!(!decision.valid_for(&turn));
        turn.actions_remaining = 1;
        turn.capabilities.clear();
        assert!(!decision.valid_for(&turn));
    }

    #[test]
    fn rejects_paths_and_shell_syntax_as_provider_ids() {
        for id in ["../codex", "/usr/bin/sh", "a;whoami", "Agy", ""] {
            assert!(!providers::valid_id(id));
        }
        assert!(providers::valid_id("local-model-2"));
    }
}
