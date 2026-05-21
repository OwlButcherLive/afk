# AFK

AFK is an Android application that provides a native dashboard + chat interface to manage AI agents running on a remote Debian server.

Connect over SSH → open a local port forwarding tunnel → chat with remote AI agents through a FastAPI Gateway.

## Architecture

```
Android (CPH2581)  ─── SSH tunnel ───→  Debian Server
    │                                       │
    │  http://127.0.0.1:<local_port>        │  Agent Gateway (FastAPI)
    │  REST (Retrofit) + WS (OkHttp)        │  :3344
    │                                       │
    │                                       ├── Hermes Agent CLI (subprocess)
    │                                       └── Stub agent (fallback)
```

- **Android app**: Kotlin/Compose/M3/MVI, single-user, no internet API
- **Tunnel**: SSHJ 0.38.0 with Conscrypt (Android 14+ JCE), Bouncy Castle disabled
- **Secret storage**: EncryptedSharedPreferences backed by Android Keystore
- **Gateway**: FastAPI + SQLite (aiosqlite), REST + WebSocket

## Repository Layout

```
afk/
├── app/                          # Android app
│   └── src/main/java/.../afk/
│       ├── core/                 # Shared: network, security, ssh
│       ├── data/                 # Local cache (ChatCache)
│       ├── domain/               # Domain models
│       └── feature/              # Feature modules
│           ├── connection/       # SSH tunnel setup
│           ├── dashboard/        # Post-connection home
│           ├── sessions/         # Session list + agent picker
│           └── chat/             # Chat screen + MVI
├── gateway/                      # FastAPI Agent Gateway
│   └── gateway/                  # Python package
│       ├── main.py               # FastAPI app
│       ├── models.py             # Pydantic schemas
│       ├── database.py           # SQLite persistence
│       ├── router.py             # REST endpoints
│       ├── ws_handler.py         # WebSocket chat handler
│       └── hermes_manager.py     # Hermes CLI subprocess adapter
└── AGENTS.md                     # Source of truth for everything above
```

## Build & Install

```bash
cd afk/
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## Gateway

See [gateway/README.md](gateway/README.md) for setup and API docs.

## AGENTS.md

Read [AGENTS.md](AGENTS.md) for the full architecture, coding standards, and workflow rules.
