# AGENTS.md

## Project
AFK is an Android application that provides a native dashboard + chat interface to manage AI agents running on a remote Debian server.

Current V1 scope:
- Android app with connection + dashboard + chat UI
- Remote connection through SSH (SSHJ 0.38.0, Conscrypt on Android 14+)
- Local port forwarding tunnel to reach the remote Agent Gateway
- Agent Gateway (FastAPI + SQLite) running on the Debian host
- REST + WebSocket communication through the SSH tunnel
- Session-based conversations with resume and agent selection
- Session list with create/reopen flows
- Real remote agent integration (Hermes Agent CLI via subprocess)
- Local message cache (ChatCache) for UI continuity across restarts

Repository root:
- Work from the afk/ directory
- Android package: com.owlbutcherlive.afk
- Gateway server: under gateway/ (FastAPI + SQLite)

## Product Intent
AFK is not a terminal emulator.
AFK is a native Android client for remotely interacting with AI agents through a secure SSH tunnel and a local forwarded port.

The mobile app must feel like:
- a dashboard
- a messaging client
- a remote control surface for agents

It must not feel like:
- a shell wrapper
- a raw terminal session
- a public web client

## Architecture Invariants
These rules are mandatory.

1. No public HTTPS API is required for V1.
2. All application traffic goes through an SSH local port forwarding tunnel.
3. Android connects to 127.0.0.1:<local_port> after the tunnel is established.
4. The remote Debian server hosts an Agent Gateway exposing a local API.
5. Session state and durable history belong on the server side, not on the Android client.
6. The Android app must remain modular enough to support multiple agents later.
7. The current implementation focus is the connection stack and the first usable UI flow.

Expected network flow:
1. Connect to Debian over SSH.
2. Authenticate with password or private key.
3. Open local port forwarding.
4. Call REST endpoints through Retrofit on http://127.0.0.1:<local_port>.
5. Open WebSockets through OkHttp on the same forwarded local endpoint.

## Tech Stack
Use these choices unless there is a build-breaking reason not to.

- Language: Kotlin only
- UI: Jetpack Compose only
- UI architecture: MVI / UDF
- State: ViewModel + StateFlow + Coroutines
- REST: Retrofit (Gson converter)
- Realtime: OkHttp WebSocket
- SSH: SSHJ 0.38.0 (Bouncy Castle disabled — Conscrypt on Android 14+)
- Secret storage: EncryptedSharedPreferences backed by Android Keystore master key
- Build tool: Gradle Kotlin DSL
- Gateway: FastAPI + aiosqlite + websockets (Python 3.11+)

## Package and Module Conventions
Keep naming simple, explicit, and boring.

Base package:
- com.owlbutcherlive.afk

Suggested package layout:
- app/
- core/common/
- core/ui/
- core/network/
- core/security/
- core/ssh/
- data/
- domain/
- feature/connection/
- feature/dashboard/
- feature/sessions/
- feature/chat/

Inside features, prefer:
- contract/   — sealed interfaces for intent, ui state, effects
- ui/         — composables
- presentation/  — ViewModel
- data/       — API wrappers (if feature-specific)

Do not create deep package trees without clear value.

## Code Style
Follow these rules consistently.

- Prefer clear names over short clever names.
- Avoid unnecessary abstractions in V1.
- Keep functions small and purpose-driven.
- Prefer immutable UI state.
- Keep business logic out of composables.
- Keep Android framework code out of domain logic when possible.
- Use Dispatchers.IO for SSH and blocking network-related work.
- Use sealed interfaces/classes for UI intents, UI state, and UI effects when useful.
- Prefer explicit state transitions over hidden side effects.
- Every new dependency must be justified by clear value.

## UI Rules
- Build a native Android experience.
- Use Material 3 Compose.
- Keep screens simple and readable.
- Handle loading, success, and error states explicitly.
- Show actionable error messages.
- Do not block the UI thread.
- Do not expose low-level SSH noise directly to the user unless it helps recovery.

## SSH and Security Rules
These are mandatory.

- SSH is the transport foundation for V1.
- Support password authentication and private key authentication.
- Prefer Ed25519 for newly generated keys.
- Never log private keys, passwords, or secret material.
- Never hardcode credentials, tokens, or host secrets.
- Store sensitive local material using Android Keystore-backed protection when feasible.
- Validate host/connection settings before attempting the tunnel.
- Expose connection state in a way the UI can observe safely.
- Tunnel lifecycle must be explicit: connect, forward, observe, close, cleanup.
- Do not leave orphan SSH sessions if a connection attempt fails.
- Treat disconnects as recoverable states.

## Networking Rules
- Retrofit is for HTTP APIs only.
- OkHttp WebSocket is for realtime messaging/events only.
- All API base URLs for V1 must point to localhost on the forwarded port.
- Avoid prematurely designing for public internet APIs.
- Keep the networking layer replaceable and testable.

## Build and Test Commands
Run commands from the afk/ directory.

Primary build check:
    ./gradlew assembleDebug

Recommended validation commands when relevant:
    ./gradlew ktlintCheck
    ./gradlew testDebugUnitTest
    ./gradlew connectedDebugAndroidTest

If a command is unavailable in the repo yet, add only what is necessary and keep the project buildable.

Gateway test (run from gateway/ directory):
    pip install -r requirements.txt && python -m pytest tests/test_gateway.py -v

## Mandatory Autonomous Loop
For every meaningful phase or milestone, follow this exact order:

1. Implement the code.
2. Run ./gradlew assembleDebug.
3. If the build fails, fix the errors immediately.
4. Repeat until the build is green.
5. Run any relevant tests for the touched area.
6. Commit only when the repository is in a healthy state.
7. Push if the remote is configured and authentication is available.
8. Continue directly to the next milestone without asking for approval.

Never move forward with a broken build.

## Commit Rules
Commit often, but only at coherent milestones.

Preferred commit style:
- feat(connection): add connection screen
- feat(ssh): add local port forwarding manager
- feat(security): add keystore-backed secret storage
- fix(network): handle websocket reconnection
- refactor(core): simplify connection state model
- docs: update setup instructions
- ci: add assembleDebug workflow
- fix(routing): prevent race condition with wrong agent selection

Before every commit:
- Build must pass
- No obvious dead code from the current milestone
- No secrets in tracked files

## Git Push Rules
- Push after each stable milestone if credentials are already configured.
- If push fails because authentication is missing or invalid, continue committing locally.
- Report the push failure clearly, but do not stop implementation for that reason alone.
- Never place tokens or passwords inside source files, gradle files, or docs.

## V1 Milestones
Work in this order unless a technical issue requires a small reordering.

1. Android skeleton and dependencies
2. SSH tunnel manager
3. Secure secret/key handling
4. REST and WebSocket client foundations
5. Connection feature contract + ViewModel
6. Connection screen in Compose
7. UI feedback and error handling
8. Basic repository wiring
9. Gateway: FastAPI server with stub agent + REST + WebSocket
10. Android: message list + chat UI with MVI
11. Android: session list + agent picker dialog
12. Gateway: session-based conversations (CRUD + WS association)
13. Gateway: Hermes Agent integration via subprocess CLI adapter
14. Fix: connection+agent race condition on session load
15. Fix: thread agentId through navigation chain

## Definition of Done for V1
V1 is done only when all the following are true:

- The project builds with ./gradlew assembleDebug
- The Android app launches
- A user can enter host, SSH port, username, auth mode, and remote API port
- The app can establish an SSH connection
- The app can open a local forwarded port
- The app can configure its REST/WebSocket layers to use the forwarded localhost endpoint
- The connection flow exposes clear loading/success/error states
- Sensitive local data is handled through a secure storage strategy
- The codebase is structured for future multi-agent support
- The repository history contains coherent commits
- A user can create a session with a real agent (Hermes CLI) and receive real responses
- Hermes readiness is validated and observable via the status endpoint

## Known Fixed Bugs
Documented here for future reference:

1. **Race condition: agent_id="default" on session load** (fix: 7bc5d82)
   - ChatViewModel.init() -> loadInitialData() set currentAgent="default" and connected WS
   - LoadSession cleared messages but NOT connectionState/currentAgent
   - User could send a message with agent_id="default" -> stub reply
   - Fix: reset connectionState=Connecting, currentAgent=null in LoadSession setState copy

2. **agentId not threaded through navigation** (fix: d4286d5)
   - Sessions have agent_id in the API but it was dropped in navigation (Screen.Chat, LoadSession intent, SessionsEffect)
   - ChatViewModel made a separate API call (fetchSessionAgentId) which failed when tunnel was down
   - Fix: pass agentId through 7 files: Screen.Chat -> ChatScreen -> ChatViewModel.LoadSession

3. **Gateway env override stripped PATH** (fix: 7bc5d82)
   - env={"HERMES_YOLO_MODE":"1"} replaced the entire environment
   - Hermes subprocess couldn't find bare "hermes" executable
   - Fix: augment os.environ instead: dict(os.environ) | {"HERMES_YOLO_MODE":"1"}

4. **Short answer fallback to raw output** (fix: 7bc5d82)
   - _extract_response fell back to raw output (with warning banners) when result <5 chars
   - A valid answer like "4" returned "⚠️  Normalized model...\ndeepseek.\n4"
   - Fix: only fall back to raw when result is empty

## Reporting Format
After each milestone, provide a short factual report:

- what was implemented
- build result
- test result if applicable
- important technical decisions
- commit created
- next milestone

Keep reports concise and delivery-focused.

## Decision Policy
When a detail is unspecified:
- choose the simplest robust option
- document the decision in code or docs if it affects architecture
- prefer maintainability over novelty
- prefer a smaller working V1 over a wider but unstable implementation

## Non-Goals for V1
Do not spend time on these unless they become necessary for buildability:

- multi-agent orchestration
- advanced dashboard analytics
- polished settings screens
- encrypted sync across devices
- public API exposure
- complex offline mode
- visual polish beyond a clean usable baseline
- Hermes persistent sessions via tmux (stateless subprocess is fine for V1)
- streaming response chunks via WebSocket
