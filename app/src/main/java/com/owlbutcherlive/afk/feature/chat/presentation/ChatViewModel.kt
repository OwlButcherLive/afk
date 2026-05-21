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
import com.owlbutcherlive.afk.domain.AgentOnlineStatus
import com.owlbutcherlive.afk.domain.ChatAgent
import com.owlbutcherlive.afk.domain.ChatEvent
import com.owlbutcherlive.afk.domain.ChatMessage
import com.owlbutcherlive.afk.domain.MessageRole
import com.owlbutcherlive.afk.feature.chat.contract.ChatConnectionState
import com.owlbutcherlive.afk.feature.chat.contract.ChatEffect
import com.owlbutcherlive.afk.feature.chat.contract.ChatIntent
import com.owlbutcherlive.afk.feature.chat.contract.ChatUiState
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class ChatViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "ChatViewModel"
    }

    private val chatApi: ChatApi = ApiClient.createApi(ChatApi::class.java)
    private val webSocketClient = WebSocketClient()

    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    private val _effects = Channel<ChatEffect>(Channel.CONFLATED)
    val effects = _effects.receiveAsFlow()

    init {
        loadInitialData()
    }

    fun processIntent(intent: ChatIntent) {
        when (intent) {
            is ChatIntent.UpdateInput -> setState { copy(inputText = intent.text) }
            ChatIntent.SendMessage -> sendMessage()
            ChatIntent.Reconnect -> reconnect()
            ChatIntent.RetryLoadHistory -> {
                viewModelScope.launch { loadHistory() }
            }
            ChatIntent.Disconnect -> disconnect()
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

    private suspend fun loadAgents() {
        try {
            val response = chatApi.getAgents()
            if (response.isSuccessful) {
                val agents = response.body()?.agents ?: emptyList()
                if (agents.isNotEmpty()) {
                    val agent = agents.first()
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
        try {
            val response = chatApi.getHistory(agent = "default", limit = 50)
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
            setState {
                copy(
                    isLoadingHistory = false,
                    historyError = "Could not load history: ${e.message ?: "Unknown error"}"
                )
            }
        }
    }

    // ─── WebSocket lifecycle ───────────────────────────────────────────────

    private fun connectWebSocket() {
        val port = ConnectionSession.tunnelPort
        if (port == 0) {
            setState { copy(connectionState = ChatConnectionState.Failed) }
            return
        }

        setState { copy(connectionState = ChatConnectionState.Connecting) }

        webSocketClient.connect(port = port, path = "/ws/chat")

        // Collect typed messages from WS
        viewModelScope.launch {
            webSocketClient.messages.collect { raw ->
                val event = ChatProtocol.parse(raw)
                if (event != null) {
                    handleChatEvent(event)
                }
            }
        }

        // Collect WS connection status
        viewModelScope.launch {
            webSocketClient.connectionEvents.collect { event ->
                when (event) {
                    is WebSocketClient.WebSocketEvent.Connected -> {
                        Log.d(TAG, "WebSocket connected")
                        setState { copy(connectionState = ChatConnectionState.Connected) }
                    }

                    is WebSocketClient.WebSocketEvent.Disconnected -> {
                        Log.d(TAG, "WebSocket disconnected: ${event.code} ${event.reason}")
                        setState { copy(connectionState = ChatConnectionState.Disconnected) }
                    }

                    is WebSocketClient.WebSocketEvent.Failed -> {
                        Log.e(TAG, "WebSocket failed: ${event.message}")
                        setState {
                            copy(
                                connectionState = ChatConnectionState.Failed,
                                sendError = "Connection lost: ${event.message}"
                            )
                        }
                    }
                }
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
                // Auto-scroll will be handled by LaunchedEffect in the UI
            }

            is ChatEvent.Typing -> {
                setState { copy(isAgentTyping = event.isTyping) }
            }

            is ChatEvent.Error -> {
                Log.w(TAG, "Server error: [${event.code}] ${event.message}")
                setState { copy(sendError = event.message) }
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

        // Clear input immediately
        setState { copy(inputText = "", sendError = null) }

        // Serialize and send via WebSocket
        val payload = ChatProtocol.createMessage(agentId, text)
        val sent = webSocketClient.send(payload)
        if (!sent) {
            setState { copy(sendError = "Failed to send message — connection lost") }
        }
    }

    // ─── Reconnect ────────────────────────────────────────────────────────

    private fun reconnect() {
        webSocketClient.disconnect()
        connectWebSocket()
    }

    // ─── Disconnect ───────────────────────────────────────────────────────

    private fun disconnect() {
        webSocketClient.disconnect()
        setState {
            copy(
                messages = emptyList(),
                connectionState = ChatConnectionState.Disconnected,
                isAgentTyping = false
            )
        }
    }

    // ─── Cleanup ─────────────────────────────────────────────────────────

    override fun onCleared() {
        super.onCleared()
        webSocketClient.disconnect()
    }

    // ─── Helpers ──────────────────────────────────────────────────────────

    private fun setState(update: ChatUiState.() -> ChatUiState) {
        _state.value = _state.value.update()
    }
}
