package com.owlbutcherlive.afk.feature.chat.presentation

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.owlbutcherlive.afk.core.common.ConnectionSession
import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.network.ChatApi
import com.owlbutcherlive.afk.core.network.ChatProtocol
import com.owlbutcherlive.afk.core.network.WebSocketClient
import com.owlbutcherlive.afk.data.ChatCache
import com.owlbutcherlive.afk.domain.AgentOnlineStatus
import com.owlbutcherlive.afk.domain.ChatAgent
import com.owlbutcherlive.afk.domain.ChatEvent
import com.owlbutcherlive.afk.domain.ChatMessage
import com.owlbutcherlive.afk.domain.MessageRole
import com.owlbutcherlive.afk.feature.chat.contract.ChatConnectionState
import com.owlbutcherlive.afk.feature.chat.contract.ChatEffect
import com.owlbutcherlive.afk.feature.chat.contract.ChatIntent
import com.owlbutcherlive.afk.feature.chat.contract.ChatUiState
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class ChatViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "ChatViewModel"
        private const val MAX_RETRIES = 2
        private const val RETRY_DELAY_MS = 1500L
        private const val ERROR_DISMISS_MS = 6000L
    }

    private val chatApi: ChatApi = ApiClient.createApi(ChatApi::class.java)
    private val webSocketClient = WebSocketClient()
    private val chatCache = ChatCache(getApplication())

    private var retryCount = 0
    private var retryJob: Job? = null
    private var wsMessagesJob: Job? = null
    private var wsConnectionJob: Job? = null

    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    private val _effects = Channel<ChatEffect>(Channel.CONFLATED)
    val effects = _effects.receiveAsFlow()

    // Tracks the session's agentId so loadAgents() can select the right agent
    private var pendingAgentId: String? = null

    init {
        // Restore cached state so the user sees their last session immediately
        val cachedMessages = chatCache.loadMessages()
        val cachedDraft = chatCache.loadDraft()
        if (cachedMessages.isNotEmpty() || cachedDraft.isNotEmpty()) {
            setState {
                copy(
                    messages = cachedMessages,
                    inputText = cachedDraft,
                    isLoadingHistory = false
                )
            }
        }
        // Load default session data; LoadSession intent overrides this
        loadInitialData()
    }

    fun processIntent(intent: ChatIntent) {
        when (intent) {
            is ChatIntent.UpdateInput -> {
                setState { copy(inputText = intent.text) }
                chatCache.saveDraft(intent.text)
            }
            ChatIntent.SendMessage -> sendMessage()
            ChatIntent.Reconnect -> reconnect()
            ChatIntent.RetryLoadHistory -> {
                viewModelScope.launch { loadHistory() }
            }
            ChatIntent.ScreenResumed -> onScreenResumed()
            ChatIntent.DismissError -> setState { copy(sendError = null) }
            is ChatIntent.LoadSession -> {
                setState {
                    copy(
                        sessionId = intent.sessionId,
                        sessionTitle = intent.sessionTitle,
                        messages = emptyList(),
                        historyError = null,
                        isLoadingHistory = true,
                        connectionState = ChatConnectionState.Connecting,
                        currentAgent = null,
                        isAgentTyping = false
                    )
                }
                chatCache.clear()
                viewModelScope.launch {
                    // Fetch session details to get the correct agentId for this session
                    pendingAgentId = fetchSessionAgentId(intent.sessionId)
                    loadAgents()
                    loadHistory()
                    connectWebSocket()
                }
            }
            ChatIntent.NavigateBack -> {
                viewModelScope.launch {
                    _effects.send(ChatEffect.NavigateBack)
                }
            }
        }
    }

    // ─── Initialization ───────────────────────────────────────────────────

    private fun loadInitialData() {
        viewModelScope.launch {
            loadAgents()
            loadHistory()
            connectWebSocket()
        }
    }

    /**
     * Called when the ChatScreen becomes visible again after navigating back.
     * Triggers auto-reconnect if the WS is down but the SSH tunnel is still active.
     */
    private fun onScreenResumed() {
        val currentState = _state.value.connectionState
        if (currentState == ChatConnectionState.Disconnected && ConnectionSession.isActive) {
            Log.d(TAG, "Screen resumed with disconnected WS — auto-reconnecting")
            reconnect()
        } else if (!ConnectionSession.isActive) {
            Log.d(TAG, "Screen resumed but SSH tunnel is not active")
            setState {
                copy(
                    connectionState = ChatConnectionState.Failed,
                    sendError = null
                )
            }
        }
    }

    /**
     * Fetch the agentId for a session from the server.
     * Returns the agentId string, or null on failure.
     */
    private suspend fun fetchSessionAgentId(sessionId: String): String? {
        if (sessionId.isEmpty() || sessionId == "default") return null
        return try {
            val response = chatApi.getSession(sessionId)
            if (response.isSuccessful) {
                response.body()?.agentId
            } else {
                Log.w(TAG, "Failed to fetch session agentId: ${response.code()}")
                null
            }
        } catch (e: Exception) {
            Log.w(TAG, "Error fetching session agentId: ${e.message}")
            null
        }
    }

    private suspend fun loadAgents() {
        try {
            val response = chatApi.getAgents()
            if (response.isSuccessful) {
                val agents = response.body()?.agents ?: emptyList()
                if (agents.isNotEmpty()) {
                    // Select the agent matching the session's agentId, or fall back to first
                    val agent = if (pendingAgentId != null) {
                        agents.find { it.id == pendingAgentId }
                            ?: agents.first()
                    } else {
                        agents.first()
                    }
                    setState {
                        copy(
                            currentAgent = ChatAgent(
                                id = agent.id,
                                name = agent.name,
                                status = AgentOnlineStatus.fromApi(agent.status)
                            )
                        )
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to load agents: ${e.message}")
        }
    }

    private suspend fun loadHistory() {
        setState { copy(isLoadingHistory = true, historyError = null) }
        val sessionId = _state.value.sessionId
        if (sessionId.isEmpty()) return
        try {
            val response = chatApi.getHistory(session = sessionId, limit = 50)
            if (response.isSuccessful) {
                val messages = response.body()?.messages?.map { dto ->
                    ChatMessage(
                        id = dto.id,
                        agentId = dto.agentId,
                        role = MessageRole.fromApi(dto.role),
                        text = dto.text,
                        timestamp = dto.timestamp
                    )
                } ?: emptyList()
                setState { copy(isLoadingHistory = false, messages = messages) }
                chatCache.saveMessages(messages)
            } else {
                setState {
                    copy(
                        isLoadingHistory = false,
                        historyError = "Failed to load history (${response.code()})"
                    )
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "History load failed: ${e.message}", e)
            val tunnelHint = if (!ConnectionSession.isActive) {
                " SSH tunnel may not be active."
            } else ""
            setState {
                copy(
                    isLoadingHistory = false,
                    historyError = "Could not load history: ${e.message ?: "Unknown error"}.$tunnelHint"
                )
            }
        }
    }

    // ─── WebSocket lifecycle ───────────────────────────────────────────────

    private fun connectWebSocket() {
        if (!ConnectionSession.isActive) {
            setState {
                copy(
                    connectionState = ChatConnectionState.Failed,
                    sendError = "SSH tunnel is not active. Reconnect from the Dashboard first."
                )
            }
            return
        }

        val port = ConnectionSession.tunnelPort
        if (port == 0) {
            setState { copy(connectionState = ChatConnectionState.Failed) }
            return
        }

        setState { copy(connectionState = ChatConnectionState.Connecting) }

        webSocketClient.connect(port = port, path = "/ws/chat")

        // Cancel old collection jobs to prevent duplicate event processing
        wsMessagesJob?.cancel()
        wsConnectionJob?.cancel()

        // Collect typed messages from WS
        wsMessagesJob = viewModelScope.launch {
            webSocketClient.messages.collect { raw ->
                val event = ChatProtocol.parse(raw)
                if (event != null) {
                    handleChatEvent(event)
                }
            }
        }

        // Collect WS connection status
        wsConnectionJob = viewModelScope.launch {
            webSocketClient.connectionEvents.collect { event ->
                when (event) {
                    is WebSocketClient.WebSocketEvent.Connected -> {
                        Log.d(TAG, "WebSocket connected")
                        retryCount = 0
                        retryJob?.cancel()
                        setState { copy(connectionState = ChatConnectionState.Connected, sendError = null) }
                    }

                    is WebSocketClient.WebSocketEvent.Disconnected -> {
                        Log.d(TAG, "WebSocket disconnected: ${event.code} ${event.reason}")
                        setState { copy(connectionState = ChatConnectionState.Disconnected) }
                    }

                    is WebSocketClient.WebSocketEvent.Failed -> {
                        Log.e(TAG, "WebSocket failed: ${event.message}")
                        handleConnectionFailure(event.message)
                    }
                }
            }
        }
    }

    private fun handleConnectionFailure(message: String) {
        // Check if tunnel is still alive
        if (!ConnectionSession.isActive) {
            setState {
                copy(
                    connectionState = ChatConnectionState.Failed,
                    sendError = "SSH tunnel disconnected. Reconnect from the Dashboard."
                )
            }
            return
        }

        // Retry with backoff
        if (retryCount < MAX_RETRIES) {
            retryCount++
            Log.d(TAG, "Retrying connection (attempt $retryCount/$MAX_RETRIES)...")
            setState { copy(connectionState = ChatConnectionState.Connecting) }
            retryJob?.cancel()
            retryJob = viewModelScope.launch {
                delay(RETRY_DELAY_MS)
                webSocketClient.disconnect()
                connectWebSocket()
            }
        } else {
            setState {
                copy(
                    connectionState = ChatConnectionState.Failed,
                    sendError = "Could not connect to chat after $MAX_RETRIES attempts."
                )
            }
        }
    }

    // ─── Event handling ───────────────────────────────────────────────────

    private fun handleChatEvent(event: ChatEvent) {
        when (event) {
            is ChatEvent.Message -> {
                val message = ChatMessage(
                    id = event.id,
                    agentId = event.agentId,
                    role = event.role,
                    text = event.text,
                    timestamp = event.timestamp
                )
                setState { copy(messages = messages + message, sendError = null) }
                chatCache.saveMessages(_state.value.messages)
            }

            is ChatEvent.Typing -> {
                setState { copy(isAgentTyping = event.isTyping) }
            }

            is ChatEvent.Error -> {
                Log.w(TAG, "Server error: [${event.code}] ${event.message}")
                setSendError(event.message)
            }

            is ChatEvent.AgentStatus -> {
                setState {
                    copy(
                        currentAgent = currentAgent?.copy(
                            status = event.status
                        )
                    )
                }
            }
        }
    }

    // ─── Send message ────────────────────────────────────────────────────

    private fun sendMessage() {
        val text = _state.value.inputText.trim()
        if (text.isEmpty()) return

        val agentId = _state.value.currentAgent?.id ?: "default"

        // Check connection BEFORE clearing input so the user doesn't lose their draft
        val connectionState = _state.value.connectionState
        if (connectionState != ChatConnectionState.Connected) {
            setSendError("Cannot send — chat is not connected.")
            return
        }

        // Clear input immediately
        setState { copy(inputText = "", sendError = null) }

        val sessionId = _state.value.sessionId
        val payload = ChatProtocol.createMessage(sessionId, agentId, text)
        val sent = webSocketClient.send(payload)
        if (!sent) {
            setSendError("Failed to send message — connection lost.")
        }
    }

    // ─── Reconnect ────────────────────────────────────────────────────────

    private fun reconnect() {
        retryCount = 0
        retryJob?.cancel()
        webSocketClient.disconnect()
        connectWebSocket()
    }

    // ─── Cleanup ─────────────────────────────────────────────────────────

    override fun onCleared() {
        super.onCleared()
        retryJob?.cancel()
        webSocketClient.disconnect()
        // Persist any unsaved state
        chatCache.saveDraft(_state.value.inputText)
        chatCache.saveMessages(_state.value.messages)
    }

    // ─── Helpers ──────────────────────────────────────────────────────────

    private fun setState(update: ChatUiState.() -> ChatUiState) {
        _state.value = _state.value.update()
    }

    /**
     * Set a send error and auto-dismiss it after ERROR_DISMISS_MS.
     */
    private fun setSendError(message: String) {
        setState { copy(sendError = message) }
        viewModelScope.launch {
            delay(ERROR_DISMISS_MS)
            // Only clear if the error hasn't been replaced
            if (_state.value.sendError == message) {
                setState { copy(sendError = null) }
            }
        }
    }
}
