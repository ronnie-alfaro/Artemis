mod context_builder;
mod providers;

use std::{
    collections::{BTreeMap, HashMap, HashSet, VecDeque},
    sync::Arc,
    time::{Duration, Instant},
};

use axum::{
    extract::{DefaultBodyLimit, State},
    http::{HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use context_builder::{ContextBuilder, ContextInput, ContextPackage};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::{Mutex, Semaphore};

#[derive(Clone)]
struct Bridge {
    cooldown: Arc<Mutex<HashMap<String, Instant>>>,
    slots: Arc<Semaphore>,
    verified: Arc<Mutex<HashSet<String>>>,
    cache: Arc<Mutex<VecDeque<(String, ContextPackage)>>>,
}

#[derive(Deserialize)]
struct Turn {
    providers: Vec<String>,
    prompt: String,
    capabilities: Vec<String>,
    actions_remaining: u8,
    #[serde(default)]
    contexts: BTreeMap<String, ContextInput>,
    #[serde(default)]
    scope: String,
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
    attempts: Vec<Attempt>,
}

#[derive(Serialize)]
struct Attempt {
    provider: String,
    estimated_tokens: Option<usize>,
    baseline_tokens: Option<usize>,
    sections: Vec<context_builder::Section>,
    context_ms: u128,
    latency_ms: u128,
    status: &'static str,
    usage: Option<providers::Usage>,
    cache_hit: bool,
}

fn context_authorized(headers: &HeaderMap) -> bool {
    let Ok(secret) = std::env::var("ARTEMIS_CONTEXT_TOKEN") else {
        return false;
    };
    let Some(value) = headers.get("x-artemis-context-token") else {
        return false;
    };
    let bytes = value.as_bytes();
    secret.len() >= 32
        && secret.len() == bytes.len()
        && secret
            .bytes()
            .zip(bytes)
            .fold(0, |difference, (a, b)| difference | (a ^ b))
            == 0
}

#[derive(Deserialize)]
struct Preview {
    provider: String,
    context: ContextInput,
}

async fn preview(
    headers: HeaderMap,
    Json(preview): Json<Preview>,
) -> Result<Json<ContextPackage>, StatusCode> {
    if !context_authorized(&headers) {
        return Err(StatusCode::UNAUTHORIZED);
    }
    ContextBuilder::build(&preview.context, &preview.provider)
        .map(Json)
        .ok_or(StatusCode::UNPROCESSABLE_ENTITY)
}

async fn decide_context(
    State(bridge): State<Bridge>,
    headers: HeaderMap,
    Json(turn): Json<Turn>,
) -> Result<Json<Outcome>, StatusCode> {
    if !context_authorized(&headers) {
        return Err(StatusCode::UNAUTHORIZED);
    }
    if turn.contexts.is_empty() {
        return Err(StatusCode::UNPROCESSABLE_ENTITY);
    }
    dispatch_turn(bridge, turn).await
}

async fn decide(
    State(bridge): State<Bridge>,
    Json(turn): Json<Turn>,
) -> Result<Json<Outcome>, StatusCode> {
    if !turn.contexts.is_empty() {
        return Err(StatusCode::UNPROCESSABLE_ENTITY);
    }
    dispatch_turn(bridge, turn).await
}

async fn dispatch_turn(bridge: Bridge, turn: Turn) -> Result<Json<Outcome>, StatusCode> {
    let Ok(slot) = bridge.slots.clone().try_acquire_owned() else {
        return Ok(Json(Outcome::default()));
    };
    // Complete cleanup even when the caller disconnects during a CLI invocation.
    let outcome = tokio::spawn(async move {
        let _slot = slot;
        dispatch(bridge, turn).await
    })
    .await
    .unwrap_or_default();
    Ok(Json(outcome))
}

async fn dispatch(bridge: Bridge, turn: Turn) -> Outcome {
    let mut attempts = Vec::new();
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
        let start = Instant::now();
        let context = turn.contexts.get(provider);
        let (package, cache_hit) = if let Some(context) = context {
            if context
                .settings
                .get(provider)
                .is_some_and(|settings| settings.cache)
                && !turn.scope.is_empty()
            {
                let key = format!(
                    "{}\0{}\0{}",
                    turn.scope,
                    provider,
                    serde_json::to_string(context).unwrap_or_default()
                );
                let mut cache = bridge.cache.lock().await;
                if let Some((_, value)) = cache.iter().find(|(cached, _)| cached == &key) {
                    (Some(value.clone()), true)
                } else {
                    let value = ContextBuilder::build(context, provider);
                    if let Some(package) = &value {
                        if cache.len() >= 8 {
                            cache.pop_front();
                        }
                        cache.push_back((key, package.clone()));
                    }
                    (value, false)
                }
            } else {
                (ContextBuilder::build(context, provider), false)
            }
        } else {
            (None, false)
        };
        let mut attempt = Attempt {
            provider: provider.clone(),
            estimated_tokens: package.as_ref().map(|value| value.estimated_tokens),
            baseline_tokens: package.as_ref().map(|value| value.baseline_tokens),
            sections: package
                .as_ref()
                .map_or_else(Vec::new, |value| value.sections.clone()),
            context_ms: start.elapsed().as_millis(),
            latency_ms: 0,
            status: "failed",
            usage: None,
            cache_hit,
        };
        if context.is_some() && package.is_none() {
            attempt.status = "budget_or_config";
            attempts.push(attempt);
            continue;
        }
        let prompt = package
            .as_ref()
            .map_or(turn.prompt.as_str(), |value| value.prompt.as_str());
        let trimmed = package.as_ref().map(|value| &value.capabilities);
        let result = providers::invoke(provider, prompt).await;
        attempt.latency_ms = start.elapsed().as_millis();
        match result {
            Ok((decision, usage))
                if decision.valid_for(&turn)
                    && trimmed.is_none_or(|items| {
                        decision.capability.is_empty() || items.contains(&decision.capability)
                    }) =>
            {
                attempt.status = "ok";
                attempt.usage = usage;
                attempts.push(attempt);
                bridge.cooldown.lock().await.remove(provider);
                bridge.verified.lock().await.insert(provider.clone());
                return Outcome {
                    provider: Some(provider.clone()),
                    decision: Some(decision),
                    attempts,
                };
            }
            result => {
                attempts.push(attempt);
                let reason = result.err().unwrap_or("invalid decision");
                tracing::warn!(%provider, %reason, "provider failed");
                bridge.verified.lock().await.remove(provider);
                let mut cooldown = bridge.cooldown.lock().await;
                cooldown.retain(|_, until| *until > Instant::now());
                cooldown.insert(provider.clone(), Instant::now() + Duration::from_secs(20));
            }
        }
    }
    Outcome {
        attempts,
        ..Outcome::default()
    }
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
        .route("/v1/context/decide", post(decide_context))
        .route("/v1/context/preview", post(preview))
        .route("/v1/providers", get(status))
        .layer(DefaultBodyLimit::max(3 * 1024 * 1024))
        .with_state(Bridge {
            cooldown: Arc::default(),
            verified: Arc::default(),
            cache: Arc::default(),
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
            contexts: BTreeMap::new(),
            scope: String::new(),
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
